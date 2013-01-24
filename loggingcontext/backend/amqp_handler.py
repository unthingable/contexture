from collections import deque, namedtuple
import json
import logging
import os
import pika
from Queue import Queue, Full, Empty
import socket
import sys
import time
import threading
import uuid

LOGGER = logging.getLogger(__name__)


from loggingcontext import settings
config = settings.config['amqp_handler']

CtxTuple = namedtuple('CtxTuple', ('ctx', 'obj'))

# Room for optimization here, perhaps
def rkey(ctx, obj):
    if ctx:
        return ctx._.routing_key
    elif 'destination' in obj:
        return obj['destination']
    else:
        return 'default'


class AMQPHandler(logging.Handler):

    # EXCHANGE = 'message'
    # EXCHANGE_TYPE = 'topic'
    INTERVAL = 1

    def __init__(self, url, exchange='lc-topic', exchange_type='topic'):
        self._url = url
        self._exchange = exchange
        self._type = exchange_type
        self._queue = Queue(maxsize=100000)
        self._running = False
        env = dict(host=socket.gethostname(),
                   pid=os.getpid(),
                   argv=sys.argv,
                   )

        from loggingcontext.context import LoggingContext
        self.ctx = LoggingContext(context=env, logger=LOGGER, silent=True)

        self.emit_from_context(self.ctx, self.ctx.context)

    def connect(self):
        return pika.SelectConnection(pika.URLParameters(self._url),
                                     self.on_connection_open)

    def on_connection_closed(self, method_frame):
        """This method is invoked by pika when the connection to RabbitMQ is
        closed unexpectedly. Since it is unexpected, we will reconnect to
        RabbitMQ if it disconnects.

        :param pika.frame.Method method_frame: The method frame from RabbitMQ

        """
        LOGGER.warning('Server closed connection, reopening: (%s) %s',
                       method_frame.method.reply_code,
                       method_frame.method.reply_text)
        self._channel = None
        self._connection = self.connect()

    def on_connection_open(self, unused_connection):
        """This method is called by pika once the connection to RabbitMQ has
        been established. It passes the handle to the connection object in
        case we need it, but in this case, we'll just mark it unused.

        :type unused_connection: pika.SelectConnection

        """
        LOGGER.debug('Connection opened')
        self._connection.add_on_close_callback(self.on_connection_closed)
        self.open_channel()

    def on_channel_closed(self, method_frame):
        """Invoked by pika when RabbitMQ unexpectedly closes the channel.
        Channels are usually closed if you attempt to do something that
        violates the protocol, such as redeclare an exchange or queue with
        different paramters. In this case, we'll close the connection
        to shutdown the object.

        :param pika.frame.Method method_frame: The Channel.Close method frame

        """
        LOGGER.warning('Channel was closed: (%s) %s',
                       method_frame.method.reply_code,
                       method_frame.method.reply_text)
        self._connection.close()

    def on_channel_open(self, channel):
        """This method is invoked by pika when the channel has been opened.
        The channel object is passed in so we can make use of it.

        Since the channel is now open, we'll declare the exchange to use.

        :param pika.channel.Channel channel: The channel object

        """
        LOGGER.debug('Channel opened')
        self._channel = channel
        self._channel.add_on_close_callback(self.on_channel_closed)
        self.setup_exchange(self._exchange)

        # start publishing
        # self.enable_delivery_confirmations()
        self.schedule_next_message()

    def open_channel(self):
        """This method will open a new channel with RabbitMQ by issuing the
        Channel.Open RPC command. When RabbitMQ confirms the channel is open
        by sending the Channel.OpenOK RPC reply, the on_channel_open method
        will be invoked.

        """
        LOGGER.info('Creating a new channel')
        self._connection.channel(on_open_callback=self.on_channel_open)

    def on_exchange_declareok(self, exchange_name):
        pass

    def setup_exchange(self, exchange_name):
        """Setup the exchange on RabbitMQ by invoking the Exchange.Declare RPC
        command. When it is complete, the on_exchange_declareok method will
        be invoked by pika.

        :param str|unicode exchange_name: The name of the exchange to declare

        """
        LOGGER.info('Declaring exchange %s', exchange_name)
        self._channel.exchange_declare(callback=self.on_exchange_declareok,
                                       exchange=exchange_name,
                                       exchange_type=self._type,
                                       passive=True)

    def on_delivery_confirmation(self, method_frame):
        """Invoked by pika when RabbitMQ responds to a Basic.Publish RPC
        command, passing in either a Basic.Ack or Basic.Nack frame with
        the delivery tag of the message that was published. The delivery tag
        is an integer counter indicating the message number that was sent
        on the channel via Basic.Publish. Here we're just doing house keeping
        to keep track of stats and remove message numbers that we expect
        a delivery confirmation of from the list used to keep track of messages
        that are pending confirmation.

        :param pika.frame.Method method_frame: Basic.Ack or Basic.Nack frame

        """
        confirmation_type = method_frame.method.NAME.split('.')[1].lower()
        if confirmation_type == 'nack':
            LOGGER.warning('Received %s for delivery tag: %i',
                           confirmation_type,
                           method_frame.method.delivery_tag)

    def enable_delivery_confirmations(self):
        """Send the Confirm.Select RPC method to RabbitMQ to enable delivery
        confirmations on the channel. The only way to turn this off is to close
        the channel and create a new one.

        When the message is confirmed from RabbitMQ, the
        on_delivery_confirmation method will be invoked passing in a Basic.Ack
        or Basic.Nack method from RabbitMQ that will indicate which messages it
        is confirming or rejecting.

        """
        LOGGER.debug('Issuing Confirm.Select RPC command')
        self._channel.confirm_delivery(self.on_delivery_confirmation)

    def run(self):
        self._running = True
        self._connection = self.connect()
        self._connection.ioloop.start()

    def stop(self):
        """
        stop() from example. We'll be exiting uncleanly, so messages might be lost.

        Original docstring:
        Stop the example by closing the channel and connection. We
        set a flag here so that we stop scheduling new messages to be
        published. The IOLoop is started because this method is
        invoked by the Try/Catch below when KeyboardInterrupt is caught.
        Starting the IOLoop again will allow the publisher to cleanly
        disconnect from RabbitMQ.

        """
        self._running = False
        self.close_channel()
        self.close_connection()
        self._connection.ioloop.start()

    def emit(self, record, ctx=None):
        try:
            self._queue.put_nowait(CtxTuple(ctx, record))
        except Full:
            LOGGER.debug('Queue full, discarding')

    def schedule_next_message(self):
        while True:
            try:
                item = self._queue.get_nowait()
            except Empty:
                break
            self.publish_tuple(item)
        if self._running:
            self._connection.add_timeout(self.INTERVAL, self.schedule_next_message)

    def publish_tuple(self, ctxtuple):
        ctx = ctxtuple.ctx
        record = ctxtuple.obj

        record['time_out'] = time.time()
        # A little redundant, but, again, why not
        if 'time_in' in record:
            record['elapsed'] = (record['time_out'] - record['time_in'])
        record['queue'] = self._queue.qsize()

        message = json.dumps(record)
        headers = None if not ctx else ctx._.headers

        properties = pika.BasicProperties(app_id='loggingcontext.amqphandler',
                                          content_type='text/plain',
                                          headers=headers)
        # print (self._exchange, rkey(ctx, record),
        #                             message, properties)
        self._channel.basic_publish(self._exchange, rkey(ctx, record),
                                    message, properties)

    def emit_from_context(self, ctx, obj):
        '''
        A special emit() to be called by LoggingContext.
        ctx: the context in question
        obj: the object that represents the context update
        '''
        out_obj = {'obj_id': ctx._.guid,
                   'handler_id': self.ctx._.guid,
                   'time_in': time.time(),
                   'obj': obj}
        self.emit(out_obj, ctx=ctx)


def configure_handlers():
    'Return handler functions'
    handler = AMQPHandler(**config)
    thread = threading.Thread(target=handler.run)
    thread.daemon = True
    thread.start()
    return [handler.emit_from_context]


def main():
    logging.basicConfig(level=logging.DEBUG)
    example = AMQPHandler(**config)
    thread = threading.Thread(target=example.run)
    thread.daemon = True
    thread.start()
    example.emit({'blah': 'hi'})
    time.sleep(20)


def monitor():
    def on_message(channel, method_frame, header_frame, body):
        print method_frame.delivery_tag
        print body
        print
        channel.basic_ack(delivery_tag=method_frame.delivery_tag)


    connection = pika.BlockingConnection()
    channel = connection.channel()

    result = channel.queue_declare(auto_delete=True)
    queue = result.method.queue
    channel.queue_bind(queue, exchange='lc-topic', routing_key='#')
    channel.basic_consume(on_message, queue, no_ack=True)
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
    connection.close()

if __name__ == "__main__":
    monitor()
