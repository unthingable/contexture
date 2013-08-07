from contexture import __version__

import json
import logging
import os
import pika
from Queue import Queue, Full, Empty
import resource
import socket
import sys
import time
import threading
import uuid

# Don't make this __name__. Used by logging config to wire amqp handler.
LOGGER = logging.getLogger('contexture.internal')


def faux_record(obj):
    class faux:
        msg = obj
        created = time.time()
        routing_key = obj.get('routing_key', 'lc-handler')
    return faux


def qitems(queue):
    while True:
        try:
            yield queue.get_nowait()
        except Empty:
            raise StopIteration


# TODO: add heartbeat?
class AMQPHandler(logging.Handler):

    INTERVAL = 1

    # singleton stuff
    _thread = None
    _queue = None
    _channel = None
    _connection = None

    def __init__(self, url=None,
                 exchange='lc-topic',
                 exchange_type='topic',
                 user='guest',
                 password='guest',
                 host='localhost',
                 port=5672,
                 virtual_host='/',
                 headers={},
                 singleton=True,
                 maxqueue=300,
                 reconnect_wait=10):
        if url:
            self._conn_params = pika.URLParameters(url)
        else:
            creds = pika.credentials.PlainCredentials(user, password)
            self._conn_params = pika.ConnectionParameters(host=host,
                                                          port=port,
                                                          virtual_host=virtual_host,
                                                          credentials=creds)
        self._exchange = exchange
        self._headers = headers
        self._type = exchange_type
        self._running = True
        self._guid = str(uuid.uuid4())
        env = dict(host=socket.gethostname(),
                   pid=os.getpid(),
                   argv=sys.argv,
                   tid=threading.current_thread().ident,
                   contexture=__version__,
                   )
        self._headers['hostname'] = env['host']
        self._throttled = 0
        self._reconnect_wait = reconnect_wait

        # Rely on attributes resolving up to the class level
        # for singleton behavior.
        if singleton:
            target = self.__class__
        else:
            target = self
        if not target._queue or not singleton:
            target._queue = Queue(maxqueue)
            target._thread = threading.Thread(target=self.run)
        # if not target._thread.is_active():
            target._thread.daemon = True
            target._thread.start()

        self.emit_obj(env)

        logging.Handler.__init__(self)

    def connect(self):
        return pika.SelectConnection(self._conn_params,
                                     self.on_connection_open)

    def on_connection_closed(self, method_frame, *args):
        """This method is invoked by pika when the connection to RabbitMQ is
        closed unexpectedly. Since it is unexpected, we will reconnect to
        RabbitMQ if it disconnects.

        :param pika.frame.Method method_frame: The method frame from RabbitMQ

        """
        LOGGER.warning('Server closed connection, reopening: (%s)',
                       method_frame,
                       #method_frame.method.reply_text
                       )
        self._channel = None
        self._connection = self.connect()

    def on_connection_open(self, unused_connection, *args):
        """This method is called by pika once the connection to RabbitMQ has
        been established. It passes the handle to the connection object in
        case we need it, but in this case, we'll just mark it unused.

        :type unused_connection: pika.SelectConnection

        """
        LOGGER.debug('Connection opened')
        self._connection.add_on_close_callback(self.on_connection_closed)
        self.open_channel()

    def on_channel_closed(self, method_frame, *args):
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

    def on_channel_open(self, channel, *args):
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

    def on_exchange_declareok(self, exchange_name, *args):
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

    def on_delivery_confirmation(self, method_frame, *args):
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
        while True:
            try:
                self._running = True
                self._connection = self.connect()
                self._connection.ioloop.start()
            except Exception, e:
                LOGGER.info('Sleeping for %s seconds and retrying'
                            % self._reconnect_wait)
                LOGGER.exception(e)
                self._running = False
                time.sleep(self._reconnect_wait)

    def close_channel(self):
        """Invoke this command to close the channel with RabbitMQ by sending
        the Channel.Close RPC command.

        """
        if self._channel:
            LOGGER.info('Closing the channel')
            self._channel.close()
        else:
            LOGGER.debug('Channel has not been open')

    def close_connection(self):
        """This method closes the connection to RabbitMQ."""
        if self._connection:
            LOGGER.info('Closing connection')
            self._connection.close()
        else:
            LOGGER.debug('Connection has not been open')

    def stop(self):
        """
        stop() from example. We'll be exiting uncleanly, so messages might be
        lost.

        Original docstring:
        Stop the example by closing the channel and connection. We
        set a flag here so that we stop scheduling new messages to be
        published. The IOLoop is started because this method is
        invoked by the Try/Catch below when KeyboardInterrupt is caught.
        Starting the IOLoop again will allow the publisher to cleanly
        disconnect from RabbitMQ.

        """
        # Stopping from __del__ quite work, but we don't care so much.
        self.emit_obj({"stopping": True})
        self._running = False
        if self._channel:
            self.close_channel()
        if self._connection:
            self.close_connection()
            self._connection.ioloop.start()

    def emit(self, record):
        try:
            self._queue.put_nowait(record)
        except Full:
            if self._throttled == 0:
                size = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                LOGGER.warning('Queue full, discarding. Used %sK', size)
            self._throttled += 1

    def emit_obj(self, obj):
        self.emit(faux_record(obj))

    def publish_items(self):
        # Check before popping
        if self._channel:
            for item in qitems(self._queue):
                self.publish_record(item)
                self._queue.task_done()
            if self._throttled > 0:
                LOGGER.warning('Queue overflow recovered, %s messages lost'
                               % self._throttled)
                self._throttled = 0
                self.publish_record(faux_record({'recovered': self._throttled}))
        else:
            LOGGER.warning('No channel, keeping messages')

    def schedule_next_message(self):
        self.publish_items()
        # if self._running:
        self._connection.add_timeout(self.INTERVAL, self.schedule_next_message)

    def publish_record(self, record):
        obj = record.msg

        # Sometimes regular logging messages find their way into the queue
        # (by misconfiguration, for example). Ignore them.
        if not isinstance(obj, dict):
            return

        obj['time_out'] = time.time()
        obj['time_in'] = record.created
        # A little redundant, but, again, why not
        obj['qtime'] = (obj['time_out'] - obj['time_in'])
        obj['qlen'] = self._queue.qsize()
        obj['handler_id'] = self._guid

        headers = self._headers.copy()
        headers.update(obj.pop('headers', {}))
        # What happends if destination is None?
        destination = obj.pop('routing_key', 'default')
        exchange = obj.pop('exchange', self._exchange)

        properties = pika.BasicProperties(app_id='contexture.amqphandler',
                                          content_type='text/plain',
                                          headers=headers)
        try:
            message = json.dumps(obj, default=lambda x: repr(x))
        except Exception, e:
            message = json.dumps(dict(error=repr(e)))

        if self._channel.is_open:
            self._channel.basic_publish(exchange, destination,
                                        message, properties)
        else:
            LOGGER.debug('Discarding %s', message)

    # Well, attempt to exit cleanly.
    def __del__(self):
        self.close()

    def close(self):
        self.stop()
