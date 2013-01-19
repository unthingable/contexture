from collections import deque
import stomp
import logging
import json
from time import time
import uuid

from loggingcontext.settings import config
# from __init__ import config

log = logging.getLogger(__name__)

class MyListener(stomp.listener.ConnectionListener):
    def on_connected(self, headers, message):
        print 'connected: %s' % message

    def on_error(self, headers, message):
        print 'recieved an error %s' % message

    def on_message(self, headers, message):
        print 'recieved a message %s' % message

conn = stomp.Connection(**config['stomp_handler'])
conn.set_listener('', MyListener())
conn.start()
conn.connect()


def as_obj(ctx, obj):
    return dict(msg=json.dumps(obj),
                time_in=time(),
                **destination(ctx, obj))


class StompHandler(logging.Handler):    # because why not
    def __init__(self, conn_param={}, processor=lambda x: x):
        self.processor = processor
        self.conn = stomp.Connection(**conn_param)
        self.conn.set_listener('', MyListener())
        self.queue = deque()
        self.running = True

    def run(self):
        log.debug
        while self.running:
            if not self.try_connect():
                log.debug('Connection failed, will try in 30 sec')
                time.sleep(30)
                continue

            if self.queue:
                stomp_obj = self.processor(self.queue.popleft())
                stomp_obj['time_out'] = time.time()
                # A little redundant, but why not
                stomp_obj['elapsed'] = (stomp_obj['time_out'] -
                                        stomp_obj['time_in'])
                self.conn.send(**stomp_obj)
                continue
            time.sleep(0.1)

    def try_connect(self):
        try:
            self.conn.start()
            conn.connect()
            return True
        except:
            return False

    def emit(self, record):
        self.queue.append(record)

    def emit_from_context(self, ctx, obj):
        '''
        A special emit() to be called by LoggingContext.
        ctx: the context in question
        obj: the object that represents the context update
        '''
        stomp_obj = {'context': ctx._.guid,
                     'time_in': time(),
                     'obj': obj}
        self.queue.append((ctx, obj))

def destination(ctx, obj):
    return {'destination': '/queue/test'}
    # return dict(
    #     destination = '/' + '.'.join((ctx._.name, ctx._.guid)),
    #     exchange = 'LoggingContext'
    # )


def emit(ctx, obj):
    # todo: identify emitter
    # add timing information
    conn.send(**as_obj(ctx, obj))


def configure_handlers():
    'Return handler functions'
    handler = StompHandler(conn_param=config['stomp_handler'])
    return [handler.emit_from_context]
