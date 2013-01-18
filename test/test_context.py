from cStringIO import StringIO
import logging
from loggingcontext import context
from loggingcontext.emit import collate
from nose.tools import ok_, eq_, with_setup
from random import random

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


def test_namespace():
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
    ctx = context.LoggingContext()
    print ctx._.name


def test_name_subclass():
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
    # Done properly:
    class MyWhatever2(object):
        def __init__(self):
            self.ctx = context.LoggingContext()

    mw = MyWhatever2()
    print mw.ctx._.name

# Actual logging
stream = StringIO()
emit_buffer = []
handler = logging.StreamHandler(stream)

real_emit = context.emit


def mock_emit(ctx, obj):
    emit_buffer.append((ctx, obj))


def setup():
    log.addHandler(handler)
    stream.reset()
    stream.truncate()
    del emit_buffer[:]
    context.emit = mock_emit


def teardown():
    log.removeHandler(handler)
    context.emit = real_emit


@with_setup(setup, teardown)
def test_logging():
    ctx = context.LoggingContext(logger=log)
    ctx.foo = 1
    ok_('foo' in stream.getvalue())


@with_setup(setup, teardown)
def test_context_emit():
    # We can supply initial context
    ctx = context.LoggingContext(logger=log, context=dict(x=4))
    ctx.foo = 'bar'
    db = collate(emit_buffer)
    eq_(len(db), 1)
    eq_(db[ctx]['foo'], 'bar')
    eq_(db[ctx]['x'], 4)

    prev_len = len(emit_buffer)
    ctx.x = 1
    ok_(len(emit_buffer) > prev_len)
    db = collate(emit_buffer)
    eq_(len(db), 1)
    eq_(db[ctx]['x'], 1)


@with_setup(setup, teardown)
def test_context_emit_ignore():
    ctx = context.LoggingContext(logger=log, ignore=('foo',))
    prev_log_len = len(stream.getvalue())
    prev_emit_len = len(emit_buffer)

    ctx.foo = 5
    eq_(len(emit_buffer), prev_emit_len)
    eq_(len(stream.getvalue()), prev_log_len)
