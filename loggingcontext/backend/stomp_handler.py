from collections import deque, namedtuple
import json
import logging
import os
import socket
import stomp
import sys
import time
import threading
import uuid

# from loggingcontext.context import LoggingContext
from loggingcontext import settings
# config = settings.config['stomp_handler']

log = logging.getLogger(__name__)

CtxTuple = namedtuple('CtxTuple', ('ctx', 'obj'))

class MyListener(stomp.listener.ConnectionListener):
    def on_connected(self, headers, message):
        log.debug('connected: %s' % message)

    def on_error(self, headers, message):
        log.debug('recieved an error %s' % message)

    def on_message(self, headers, message):
        log.debug('recieved a message %s' % message)


# conn = stomp.Connection(**config['stomp_handler'])
# conn.set_listener('', MyListener())
# conn.start()
# conn.connect()


# Room for optimization here, perhaps
def destination(ctx, obj):
    root = '/exchange/lc-topic'
    if ctx:
        dest = {'destination': "%s/%s" % (root, ctx._.name)}
        if ctx._.headers:
            dest['headers'] = ctx._.headers
        return dest
    elif 'destination' in obj:
        return {'destination': obj['destination']}
    else:
        return {'destination': root + '/none'}


def _send_tuple(conn, ctx_tuple):
    stomp_obj = ctx_tuple.obj
    stomp_obj['time_out'] = time.time()
    # A little redundant, but, again, why not
    stomp_obj['elapsed'] = (stomp_obj['time_out'] -
                            stomp_obj['time_in'])
    conn.send(json.dumps(stomp_obj),
                   **destination(*ctx_tuple))


class StompHandler(logging.Handler):    # because why not
    def __init__(self, conn_param={}, processor=lambda x: x):
        self.processor = processor
        self.conn = stomp.Connection(**conn_param)
        self.conn.set_listener('', MyListener())
        self.queue = deque()

        env = dict(host=socket.gethostname(),
                   pid=os.getpid(),
                   argv=sys.argv,
                   )
        from loggingcontext.context import LoggingContext
        self.ctx = LoggingContext(context=env, logger=log, silent=True)

        self.stomp_thread = threading.Thread(target=self._run)
        self.stomp_thread.start()

        self.emit_from_context(self.ctx, env)

    def _run(self):
        self.ctx.running = True
        while self.ctx.running:
            if not self.conn.is_connected():
                if not self.try_connect():
                    log.debug('Connection failed, will try in 30 sec')
                    time.sleep(config['connect_timeout'])
                    continue

            if self.queue:
                ctx_tuple = self.processor(self.queue.popleft())
                _send_tuple(conn, ctx_tuple)
                continue
            time.sleep(config['sleep'])
        log.debug('Exiting')

    def try_connect(self):
        try:
            if self.conn.is_connected():
                return True
            self.conn.start()
            self.conn.connect(wait=True)
            return True
        except Exception, e:
            log.exception(e)
            return False

    def emit(self, record, ctx=None):
        if len(self.queue) > config['max_queue']:
            log.critical("Queue size %s, discarding message" % len(self.queue))
        self.queue.append(CtxTuple(ctx, record))

    def emit_from_context(self, ctx, obj):
        '''
        A special emit() to be called by LoggingContext.
        ctx: the context in question
        obj: the object that represents the context update
        '''
        stomp_obj = {'obj_id': ctx._.guid,
                     'handler_id': self.ctx._.guid,
                     'time_in': time.time(),
                     'obj': obj}
        self.emit(stomp_obj, ctx=ctx)


def configure_handlers():
    'Return handler functions'
    handler = StompHandler(conn_param=config['connection'])
    return [handler.emit_from_context]
