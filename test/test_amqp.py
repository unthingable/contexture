from contexture.backend import amqp_handler
from mock import Mock, MagicMock, patch
from nose.tools import eq_
import pika
import time

#config = {'contexture.backend.amqp_handler.AMQPHandler._channel'}

def fake_ioloop(*args):
    time.sleep(2)

@patch.object(amqp_handler.AMQPHandler, '_channel', autospec=True)
#@patch.object(amqp_handler.AMQPHandler, )
@patch('pika.connection.Connection.connect', autospec=True)
#@patch.object(amqp_handler, 'pika', autospec=True)
def test_amqp_singleton(conn, channel):
    handler1 = amqp_handler.AMQPHandler("amqp://guest:guest@localhost:5672/%2F")
    # handler2 = amqp_handler.AMQPHandler('')

    # handler1.emit_obj({'foo': 'bar'})

    # eq_(handler1._queue, handler2._queue)
    # eq_(handler1._thread, handler2._thread)
    time.sleep(2)
    print len(channel.mock_calls)
