from cStringIO import StringIO
from pkg_resources import resource_filename
import logging
import logging.config

logging.config.fileConfig(resource_filename(__name__, 'test.conf'))

from loggingcontext import context
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
merchant_id
merchant_product_id
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


class MyC(context.LoggingContext):
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
    ctx = context.LoggingContext(logger=log)
    for word in member_words:
        thing = random()
        setattr(ctx, word, thing)
        eq_(getattr(ctx, word), thing)


def test_reserved_assign():
    ctx = context.LoggingContext()
    for word in reserved_words:
        try:
            setattr(ctx, word, 123)
            ok_(False)  # not ok
        except AttributeError:
            ok_(True)  # all good


def test_reserved_subclass():
    "Subclasses should not create class variables using reserved keywords"
    class MyCtx(context.LoggingContext):
        context = 1

    try:
        MyCtx()
        ok_(False)
    except AttributeError, e:
        ok_('context' in e.message)


def test_name_standalone():
    # We can use context on its own
    ctx = context.LoggingContext()
    print ctx._.name


def test_name_subclass():
    # We can extend context
    mc = MyC()
    print mc._.name


def test_name_subclass_class():
    # Here LoggingContext cannot tell where it is,
    # so either give it a proper name or use from __init__.

    # Note that it is generally not recommended to use this at
    # class level, so don't do this:
    class MyWhatever(object):
        ctx = context.LoggingContext()

    mw = MyWhatever()
    print mw.ctx._.name


def test_name_subclass_init():
    # We can use context inside another class and it will know.
    # Done properly:
    class MyWhatever2(object):
        def __init__(self):
            self.ctx = context.LoggingContext()

    mw = MyWhatever2()
    print mw.ctx._.name


def test_name_set():
    # We can use our own name
    ctx = context.LoggingContext(name='foo.bar')
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


def setup():
    context.backend_logger.addHandler(backend_handler)
    log.addHandler(out_handler)
    stream.reset()
    stream.truncate()
    del emit_buffer[:]


def teardown():
    context.backend_logger.removeHandler(backend_handler)
    log.removeHandler(out_handler)

@with_setup(setup, teardown)
def test_logging():
    ctx = context.LoggingContext(logger=log)
    ctx.foo = 1
    ok_('foo' in stream.getvalue())


@with_setup(setup, teardown)
def test_logging_msg():
    # We can do messages, too
    ctx = context.LoggingContext(logger=log)
    ctx.log.debug('ohai')
    ok_('ohai' in stream.getvalue())

    # And we can use context to format
    ctx.x = 123
    ctx.log.debug('i has {x}')
    ok_('i has 123' in stream.getvalue())


@with_setup(setup, teardown)
def test_logging_death():
    'Our death must be documented'
    ctx = context.LoggingContext(logger=log)
    prev = len(stream.getvalue())
    del ctx
    # Do not got gentle into that good night
    ok_(len(stream.getvalue()) != prev)


@with_setup(setup, teardown)
def test_context_emit():
    # We can supply initial context
    ctx = context.LoggingContext(logger=log, context=dict(x=4))
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


@with_setup(setup, teardown)
def test_context_emit_ignore():
    ctx = context.LoggingContext(logger=log, ignore=('foo',))
    prev_log_len = len(stream.getvalue())
    prev_emit_len = len(emit_buffer)

    ctx.foo = 5
    eq_(len(emit_buffer), prev_emit_len)
    eq_(len(stream.getvalue()), prev_log_len)


@with_setup(setup, teardown)
def test_emit_msg():
    ctx = context.LoggingContext(logger=log)
    ctx.log.debug('ohai')
    db = collate(emit_buffer)
    eq_(db[ctx._.guid]['message'], 'ohai')


import time
def real_emit():
    with context.LoggingContext() as ctx:
        for x in range(600):
            ctx.real_deal = x
            # time.sleep(0.01)
        # Let the handler finish
    time.sleep(2)


if __name__ == '__main__':
    print 'real_emit()'
    real_emit()
