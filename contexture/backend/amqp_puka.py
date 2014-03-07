from contexture import __version__

import json
import logging
import os
# import pika
import puka
from Queue import Queue, Full, Empty
import resource
import socket
import sys
import time
import threading
import uuid

# Don't make this __name__. Used by logging config to wire amqp handler.
LOGGER = logging.getLogger('contexture.internal')
# LOGGER.setLevel(logging.DEBUG)
LOGGER.debug("LOGGER.debug works")


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
    _client = None

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
                 reconnect_wait=10,
                 ):
        if not url:
            self._url = 'amqp://%s:%s@%s:%s%s' % (user, password, host, port, virtual_host)
        # if url:
        #     self._conn_params = pika.URLParameters(url)
        # else:
        #     creds = pika.credentials.PlainCredentials(user, password)
        #     self._conn_params = pika.ConnectionParameters(host=host,
        #                                                   port=port,
        #                                                   virtual_host=virtual_host,
        #                                                   credentials=creds)

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
            LOGGER.debug('Starting daemonized thread')
            target._thread.daemon = True
            target._thread.start()

        self.emit_obj(env)

        logging.Handler.__init__(self)

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

        try:
            message = json.dumps(obj, default=lambda x: repr(x))
        except Exception, e:
            message = json.dumps(dict(error=repr(e)))

        if self._running and self._client:
            LOGGER.debug("publishing %s", message)
            return self._client.basic_publish(exchange=exchange, routing_key=destination,
                                              body=message, headers=headers)
        else:
            LOGGER.debug('Discarding %s', message)

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
        batch = 0
        promise = None
        if self._running:
            for item in qitems(self._queue):
                LOGGER.debug('Publishing %r', item)
                promise = self.publish_record(item)
                # self._queue.task_done()
                batch += 1
            if self._throttled > 0:
                LOGGER.warning('Queue overflow recovered, %s messages lost'
                               % self._throttled)
                self._throttled = 0
                self.publish_record(faux_record({'recovered': self._throttled}))
        else:
            LOGGER.warning('No channel, keeping messages')
        return batch, promise

    def schedule_burst(self, t, result):
        while True and self._running:
            batch, promise = self.publish_items()
            if batch:
                LOGGER.debug("Purging %s queue items (promise %s)", batch, promise)
                for x in xrange(batch):
                    self._queue.task_done()
            else:
                time.sleep(1)
            if promise:
                LOGGER.debug("Setting promised callback")
                self._client.set_callback(promise, self.schedule_burst)
                break

    def on_connect(self, t, result):
        LOGGER.debug("Declaring exchange %s", self._exchange)
        self._client.exchange_declare(exchange=self._exchange,
                                      type=self._type,
                                      durable=True,
                                      callback=self.schedule_burst)

    def run(self):
        while True:
            try:
                self._running = True
                self._client = puka.Client(self._url)
                self._client.connect(callback=self.on_connect)
                # self._client.set_callback(promise, self.schedule_burst)
                LOGGER.debug("Starting client loop")
                self._client.loop()
                LOGGER.debug("Client loop stopped.")
            except Exception, e:
                if self._reconnect_wait:
                    LOGGER.info('Sleeping for %s seconds and retrying'
                                % self._reconnect_wait)
                    # LOGGER.exception(e)
                    self._running = False
                    time.sleep(self._reconnect_wait)
                else:
                    LOGGER.debug("No reconnect, KTHXBAI")

    def queue_join(self):
        if self._running:
            self._queue.join()

    def stop(self):
        self.emit_obj({"stopping": True})
        if self._running:
            self._running = False
            LOGGER.debug("running = False")

    def __del__(self):
        self.close()

    def close(self):
        self.stop()
