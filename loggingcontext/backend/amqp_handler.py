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

LOGGER = logging.getLogger()


def faux_record(obj):
    class faux:
        msg = obj
        created = time.time()
        routing_key = obj.get('routing_key', 'lc-handler')
    return faux


# def publish(obj, headers=None, exchange='default', routing_key='lc-handler'):
#     'Shorthand to publish anything anywhere'


# TODO: add heartbeat?
class AMQPHandler(logging.Handler):

    INTERVAL = 1

    def __init__(self, url, exchange='lc-topic', exchange_type='topic', headers={}):
        self._url = url
        self._exchange = exchange
        self._headers = headers
        self._type = exchange_type
        self._queue = Queue(maxsize=100000)
        self._running = True
        self._guid = str(uuid.uuid4())
        env = dict(host=socket.gethostname(),
                   pid=os.getpid(),
                   argv=sys.argv,
                   )

        thread = threading.Thread(target=self.run)
        thread.daemon = True
        thread.start()

        self.emit(faux_record(env))

        logging.Handler.__init__(self)

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

    def open_channel(self):
        """This method will open a new channel with RabbitMQ by issuing the
        Channel.Open RPC command. When RabbitMQ confirms the channel is open
        by sending the Channel.OpenOK RPC reply, the on_channel_open method
        will be invoked.

        """
        LOGGER.info('Creating a new channel')
        self._connection.channel(on_open_callback=self.on_channel_open)

    def on_exchange_declareok(self, exchange_name):
        # start publishing
        # self.enable_delivery_confirmations()
        self.schedule_next_message()

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
                                       durable=True
                                       )

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
        try:
            self._running = True
            self._connection = self.connect()
            self._connection.ioloop.start()
        except pika.exceptions.AMQPConnectionError:
            self._running = False
            # Free up queued objects
            with self._queue.mutex:
                self._queue.queue.clear()
            raise

    def close_channel(self):
        """Invoke this command to close the channel with RabbitMQ by sending
        the Channel.Close RPC command.

        """
        LOGGER.info('Closing the channel')
        self._channel.close()

    def close_connection(self):
        """This method closes the connection to RabbitMQ."""
        LOGGER.info('Closing connection')
        self._connection.close()

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
        # Stopping from __del__ quite work, but we don't care so much.
        self.emit(faux_record({"stopping": True}))
        self._running = False
        self.close_channel()
        self.close_connection()
        self._connection.ioloop.start()

    def emit(self, record):
        try:
            self._queue.put_nowait(record)
        except Full:
            LOGGER.warning('Queue full, discarding')

    def filter(self, record):
        return int(self._running)

    def schedule_next_message(self):
        while True:
            try:
                item = self._queue.get_nowait()
            except Empty:
                break
            self.publish_record(item)
        if self._running:
            self._connection.add_timeout(self.INTERVAL, self.schedule_next_message)

    def publish_record(self, record):
        obj = record.msg

        obj['time_out'] = time.time()
        obj['time_in'] = record.created
        # A little redundant, but, again, why not
        obj['elapsed'] = (obj['time_out'] - obj['time_in'])
        obj['queue'] = self._queue.qsize()
        obj['handler_id'] = self._guid

        headers = self._headers.copy()
        headers.update(obj.pop('headers', {}))
        # What happends if destination is None?
        destination = obj.pop('routing_key', 'default')
        exchange = obj.pop('exchange', self._exchange)
        message = json.dumps(obj)

        properties = pika.BasicProperties(app_id='loggingcontext.amqphandler',
                                          content_type='text/plain',
                                          headers=headers)
        self._channel.basic_publish(exchange, destination,
                                    message, properties)

    # Well, attempt to exit cleanly.
    def __del__(self):
        self.stop()


def monitor(url=None, keys=['#'], exchange='lc-topic'):
    def on_message(channel, method_frame, header_frame, body):
        print method_frame.delivery_tag, method_frame, header_frame
        print body
        print
        # channel.basic_ack(delivery_tag=method_frame.delivery_tag)

    params = None
    if url:
        params = pika.URLParameters(url)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()

    result = channel.queue_declare(auto_delete=True)
    queue = result.method.queue
    for key in keys:
        channel.queue_bind(queue, exchange=exchange, routing_key=key)
    channel.basic_consume(on_message, queue, no_ack=True)
    try:
        print "Listening for %s on %s on %s" % (keys, exchange, url)
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
    connection.close()


def monitor_cmd():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-k', '--keys', default='#', help="binding keys")
    parser.add_argument('-e', '--exchange', default='lc-topic', help="exchange")
    parser.add_argument('-H', '--host', default='localhost', help="hostname")
    parser.add_argument('-u', '--url',
                        help="Fully qualified url (overrides hostname)")

    args = parser.parse_args()
    url = args.url or 'amqp://guest:guest@%s:5672/%%2F' % args.host
    monitor(keys=args.keys.split(), exchange=args.exchange, url=url)
