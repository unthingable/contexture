from cStringIO import StringIO
import logging


from contexture import context
from nose.tools import ok_, eq_, with_setup
from random import random
import json

member_words = '''addheaders
add_to_cart_page
available
bind
change_url
code
csrf_token
display
html
itemid
length
num_avail
offer_id
page
page_no
request
result_queue
store
store_id
tag
text
url
value
variation_id'''.split()

reserved_words = 'context log update _'.split()

log = logging.getLogger(__name__)


class MyC(context.Context):
    foo = 1


def collate(stream):
    '''
    Given (context, dict) pairs, assemble the object incrementally.
    Return context->object dict.
    '''
    db = {}
    for d in stream:
        if 'obj' not in d:
            continue
        sobj = d['obj']
        sobj_id = d['obj_id']
        obj = db.setdefault(sobj_id, {})
        obj.update(sobj)
    return db


def collated(stream, key=None):
    'Convenience wrapper, return the first collated object.'
    db = collate(stream)
    if key:
        return db[key]
    else:
        return db.values()[0]


def test_collate():
    stream = [dict(obj={"foo": 1}, obj_id=5)]
    db = collate(stream)
    eq_(db, {5: {'foo': 1}})


def test_collate_2():
    stream = [dict(obj={"foo": 1}, obj_id=5),
              dict(obj={"bar": 2}, obj_id=5),
              dict(obj={"foo": 3}, obj_id=5),
              ]
    db = collate(stream)
    eq_(db, {5: {'foo': 3, 'bar': 2}})


def test_namespace():
    # We can supply our our logger
    ctx = context.Context(logger=log)
    for word in member_words:
        thing = random()
        setattr(ctx, word, thing)
        eq_(getattr(ctx, word), thing)


def test_reserved_assign():
    ctx = context.Context()
    for word in reserved_words:
        try:
            setattr(ctx, word, 123)
            ok_(False)  # not ok
        except AttributeError:
            ok_(True)  # all good


def test_reserved_subclass():
    "Subclasses should not create class variables using reserved keywords"
    class MyCtx(context.Context):
        context = 1

    try:
        MyCtx()
        ok_(False)
    except AttributeError, e:
        ok_('context' in e.message)


def test_name_standalone():
    # We can use context on its own
    ctx = context.Context()
    print ctx._.name


def test_name_subclass():
    # We can extend context
    mc = MyC()
    print mc._.name


def test_name_subclass_class():
    # Here Context cannot tell where it is,
    # so either give it a proper name or use from __init__.

    # Note that it is generally not recommended to use this at
    # class level, so don't do this:
    class MyWhatever(object):
        ctx = context.Context()

    mw = MyWhatever()
    print mw.ctx._.name


def test_name_subclass_init():
    # We can use context inside another class and it will know.
    # Done properly:
    class MyWhatever2(object):
        def __init__(self):
            self.ctx = context.Context()

    mw = MyWhatever2()
    print mw.ctx._.name


def test_name_set():
    # We can use our own name
    ctx = context.Context(name='foo.bar')
    eq_(ctx._.name, 'foo.bar')


stream = StringIO()  # log output
emit_buffer = []
out_handler = logging.StreamHandler(stream)


class BHandler(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)

    def emit(self, record):
        emit_buffer.append(record.msg)

backend_handler = BHandler()
backend_handler.setLevel(logging.DEBUG)
backend_logger = None


def setup():
    global backend_logger
    backend_logger = context.backend_logger
    context.backend_logger = logging.getLogger('contexture.test')
    context.backend_logger.addHandler(backend_handler)
    log.addHandler(out_handler)
    stream.reset()
    stream.truncate()
    del emit_buffer[:]


def teardown():
    # context.backend_logger.removeHandler(backend_handler)
    context.backend_logger = backend_logger
    log.removeHandler(out_handler)


@with_setup(setup, teardown)
def test_logging():
    ctx = context.Context(logger=log)
    ctx.foo = 1
    ok_('foo' in stream.getvalue())


@with_setup(setup, teardown)
def test_logging_msg():
    # We can do messages, too
    ctx = context.Context(logger=log)
    ctx.log.debug('ohai')
    ok_('ohai' in stream.getvalue())

    # And we can use context to format
    ctx.x = 123
    ctx.log.debug('i has {x}')
    ok_('i has 123' in stream.getvalue())


@with_setup(setup, teardown)
def test_logging_death():
    'Our death must be documented'
    ctx = context.Context(logger=log)
    prev = len(stream.getvalue())
    del ctx
    # Do not got gentle into that good night
    ok_(len(stream.getvalue()) != prev)


@with_setup(setup, teardown)
def test_custom_id():
    context.Context(guid='asdf')
    ok_('asdf' in collate(emit_buffer))


@with_setup(setup, teardown)
def test_lifecycle_noargs():
    eq_(len(emit_buffer), 0)
    ctx = context.Context()
    eq_(len(emit_buffer), 1)
    ctx.foo = 1
    eq_(len(emit_buffer), 2)
    del ctx
    eq_(len(emit_buffer), 3)
    print "Emitted:"
    print '\n'.join(str(x) for x in emit_buffer)


@with_setup(setup, teardown)
def test_context_emit():
    # We can supply initial context
    ctx = context.Context(logger=log, context=dict(x=4))
    ctx.foo = 'bar'
    guid = ctx._.guid
    db = collate(emit_buffer)
    eq_(len(db), 1)
    eq_(db[guid]['foo'], 'bar')
    eq_(db[guid]['x'], 4)

    prev_len = len(emit_buffer)
    ctx.x = 1
    ok_(len(emit_buffer) > prev_len, 'Buffer is supposed to grow')
    db = collate(emit_buffer)
    eq_(len(db), 1, "Collation is not supposed to grow")
    eq_(db[guid]['x'], 1)

    # Try the .update()
    prev_len = len(emit_buffer)
    ctx.update(x=2, y=3)
    ok_(len(emit_buffer) > prev_len, 'Buffer is supposed to grow')
    db = collate(emit_buffer)
    eq_(len(db), 1, "Collation is not supposed to grow")
    eq_(db[guid]['x'], 2)
    eq_(db[guid]['y'], 3)


@with_setup(setup, teardown)
def test_wrapped_properties():
    class Orig(object):
        foo = 1

        @property
        def bar(self):
            return self.foo

    obj = Orig()

    wrapped = context.Context(obj=obj)
    ok_(wrapped.bar, 1)
    eq_(wrapped.foo, 1)
    wrapped.foo = 2
    ok_(wrapped.bar, 2)
    db = collated(emit_buffer)
    eq_(db['foo'], 2)
    ok_('bar' not in db)

    # Setting a readonly property of wrapped object:
    wrapped.bar = 3
    eq_(collated(emit_buffer)['bar'], 3)
    eq_(obj.bar, 2)


@with_setup(setup, teardown)
def test_context_emit_ignore():
    ctx = context.Context(logger=log, ignore=('foo',))
    prev_log_len = len(stream.getvalue())
    prev_emit_len = len(emit_buffer)

    ctx.foo = 5
    eq_(len(emit_buffer), prev_emit_len)
    eq_(len(stream.getvalue()), prev_log_len)


@with_setup(setup, teardown)
def test_emit_msg():
    ctx = context.Context(logger=log)
    ctx.log.debug('ohai')
    #db = collate(emit_buffer)
    ok_(any(x.get('message', '') == 'ohai' for x in emit_buffer))


def real_emit():
    import time
    with context.Context(context={"foo": 123},
                                headers={"my_id": "123"}) as ctx:
        for x in range(600):
            ctx.real_deal = x
            # time.sleep(0.01)
        # Let the handler finish
    time.sleep(2)


@with_setup(setup, teardown)
def test_wrapped_object_attribute_access():
    class Blah(object):
        x = 1

        @property
        def y(self):
            return 2

        def f(self):
            return 3

    blah = Blah()
    ctx = context.Context(obj=blah)
    # Setting nonexisting attribute:
    ctx.foo = 123
    eq_(ctx.foo, 123)
    # Confirm emit
    eq_(collated(emit_buffer)['foo'], 123)
    # Properties and attributes still work
    eq_(ctx.x, 1)
    eq_(ctx.y, 2)
    # Setting a nonexisting attribute
    ctx.x = 8
    eq_(ctx.x, 8)
    eq_(blah.x, 8)
    # Confirm emit
    eq_(collated(emit_buffer)['x'], 8)

    # And now for something completely different:
    eq_(ctx.f(), 3)
    # This will shadow Blah.f():
    ctx.f = 0
    eq_(ctx.f, 0)
    eq_(collated(emit_buffer)['f'], 0)


@with_setup(setup, teardown)
def test_transient_objects():
    transient = context.Context(transient=True, context={'x': 1})
    eq_(len(emit_buffer), 1)
    del transient
    eq_(len(emit_buffer), 1)


@with_setup(setup, teardown)
def test_context_linking_by_id():
    ca = context.Context(guid='a')
    cb = context.Context(guid='b')
    ca.x = 1
    cb.linked = ca
    eq_(collate(emit_buffer)['b']['linked'], 'a')
    eq_(cb.linked.x, 1)


def flood():
    import time
    import os
    import gzip
    from itertools import islice, cycle, ifilter
    import resource

    from contexture.backend import amqp_handler
    logging.basicConfig(level=logging.DEBUG)

    print "SEVERELY flooding emitter with over 9000 messages"
    print "Starting with %sK" % resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    fixture = os.path.join(os.path.dirname(__file__), 'fixtures/bigobjects.json.gz')
    cnt = 0
    try:
        handler = context.backend_logger.handlers[0]
        for obj in islice(cycle(ifilter(None, gzip.open(fixture))), handler.MAXQUEUE * 2 + 5):
            obj = json.loads(obj)['object']
            handler.emit(amqp_handler.faux_record(obj))
            cnt += 1
            # Throttling this just a little prevents the overflow
            # time.sleep(0.0001)
    except Exception:
        print obj
        raise
    print 'pushed %s' % cnt
    time.sleep(2)


if __name__ == '__main__':
    print 'flood()'
    flood()
