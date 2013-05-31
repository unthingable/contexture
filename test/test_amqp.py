from contexture.backend import amqp_handler

import logging
from mock import Mock, patch
from nose.tools import eq_, ok_, with_setup
from pika import channel
from cStringIO import StringIO
import time
import threading

# log = logging.getLogger(__name__)
stream = StringIO()  # log output
out_handler = logging.StreamHandler(stream)
# amqp_handler.LOGGER.addHandler(out_handler)
# amqp_handler.LOGGER.setLevel(logging.DEBUG)


def setup():
    stream.reset()
    stream.truncate()
    amqp_handler.LOGGER.addHandler(out_handler)


def teardown():
    amqp_handler.LOGGER.removeHandler(out_handler)


def patched_handler(*args, **kw):
    "Return a handler that thinks it's connected"

    def fake_ioloop():
        '''
        We have to replace the native ioloop, so the callback chains
        won't fire any more. Have to do the publishing work ourselves.
        '''
        while True:
            handler.publish_items()
            time.sleep(0.1)

    def fake_run(arg):
        '''
        Skip the connection and start the loop.
        '''
        run_thread = threading.Thread(target=fake_ioloop)
        run_thread.daemon = True
        run_thread.start()

    with patch.multiple(amqp_handler.AMQPHandler, run=fake_run):
        handler = amqp_handler.AMQPHandler(*args, **kw)
        handler._channel = Mock(spec=channel.Channel)
        handler._channel.is_open = True
        return handler


def test_amqp_singleton(*args):
    handler1 = patched_handler('')
    handler2 = patched_handler('')
    handler3 = patched_handler('', singleton=False)

    handler1.emit_obj({'foo': 'bar'})
    time.sleep(0.2)

    # handler1 and 2 should have singleton queues and threads
    eq_(handler1._queue, handler2._queue)
    eq_(handler1._thread, handler2._thread)

    # handler3 should have his own
    ok_(handler1._queue != handler3._queue)
    ok_(handler1._thread != handler3._thread)

    # Visual check, expect to see two greetings and one emit
    print handler1._channel.basic_publish.call_args_list


@with_setup(setup, teardown)
def test_overflow():
    maxqueue = 3
    volley_size = 50
    handler = patched_handler('', maxqueue=maxqueue, singleton=False)
    # Cause an overflow
    for ii in range(volley_size):
        handler.emit_obj({'x': 'y'})
    # Let it recover
    time.sleep(0.2)

    handler.emit_obj({1: 2})
    time.sleep(0.2)
    out = stream.getvalue()
    print out
    print handler._channel.basic_publish.call_args_list

    eq_(out.count('recovered'), 1)
    eq_(out.count('full'), 1)
