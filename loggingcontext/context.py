from collections import deque
import logging
import stomp
from time import time
import uuid

logging.basicConfig(level=logging.DEBUG)

'''
Requirements:

1. use native logging methods
2. propagate of value changews
3.

Use case:

ctx = LoggingContext(name="mycontext")
ctx.foo = 1
ctx.update(msg="i has {foo} and {bar}",
           level=logging.DEBUG,
           bar='bar')
x ctx.log.info("for great %s", "justice")
...

with LoggingContext(context=dict(foo=1)) as ctx:
    ...
    ctx.foo = 3
'''


class _dummy_obj:
    pass


# to be used by itself _and_ extended
class LoggingContext(object):
    '''
    Reserved members:
        context
        log
        update
    '''
    # LoggingContext is not created often, so we can afford
    # to be a little expensive

    class LogProxy(object):
        def __init__(self, ctx):
            self.ctx = ctx

    # Create LogProxy logging methods
    for level_name in ('info',
                       'debug',
                       'warning',
                       'warn',
                       'error',
                       'fatal',
                       'critical'):
        level = getattr(logging, level_name.upper())

        def closure(level, name):
            def log_func(lp, *msg, **kw):
                return lp.ctx._update(msg=msg, level=level, context=kw)
            log_func.func_name = name
            return log_func

        setattr(LogProxy, level_name, closure(level, level_name))

        # def debug(self, *msg, **kw):
        #     return self.ctx._update(msg=msg, level=logging.DEBUG, context=kw)

        # def info(self, *msg, **kw):
        #     return self.ctx._update(msg=msg, level=logging.INFO, context=kw)

        # def warn(self, *msg, **kw):
        #     return self.ctx._update(msg=msg, level=logging.WARN, context=kw)

        # def warning(self, *msg, **kw):
        #     return self.ctx._update(*msg, level=logging.WARNING, context=kw)

        # def error(self, *msg, **kw):
        #     return self.ctx._update(*msg, level=logging.ERROR, context=kw)

        # def fatal(self, *msg, **kw):
        #     return self.ctx._update(*msg, level=logging.FATAL, context=kw)

        # def critical(self, *msg, **kw):
        #     return self.ctx._update(*msg, level=logging.CRITICAL, context=kw)

    def __init__(self, name=None, context={}, heartbeat=None, logger=None):
        self.context = {}
        self._ = _dummy_obj()
        self._.guid = uuid.uuid4()

        if name is None:
            name = self.__class__.__name__
        self._.name = name
        self._.created_at = time()
        self._.log = logger or logging.getLogger(name)

#        self.__.queue = deque()
#        self.terminate = False

        # Construct the log proxy
        self.log = self.LogProxy(self)

        self.update(status="born", **context)

    def _update(self, msg=[], level=logging.DEBUG, context={}):
        self.context.update(context)
        obj = dict(context)
        if msg and self._.log.isEnabledFor(level):
            if len(msg):
                msg = msg[0] % msg[1:]
            else:
                msg = msg[0]
            msg = msg.format(**self.context)
        else:
            msg = None
        if msg:
            obj['msg'] = msg
        obj['timestamp'] = time()

        # stomp send
        self.stomp(obj)

        # Log log
        if self._.log.isEnabledFor(level):
            kwstr = ', '.join("%s = %s" % x for x in context.iteritems())
            msg = '; '.join(x for x in (msg, kwstr) if x)
            self._.log.debug('%s: %s', self._.guid, msg)

    # If the namespace contention proves a nuisance, we can move
    # the methods else where (like ctx.logger.*)
    def update(self, **kw):
        return self._update(context=kw)

    def stomp(self, obj):
        pass

    def __setattr__(self, name, value):
        if name in ('_', 'context', 'log'):
            object.__setattr__(self, name, value)
        else:
            self.update(**{name: value})

    def __getattr__(self, name):
        if name not in self.context:
            raise AttributeError
        return self.context[name]

    def __str__(self):
        return "%s %s" % (self._.name, self._.guid)

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        del self

    def __del__(self):
        self.update(elapsed=(time() - self._.created_at), status="finished")
        # self.terminate = True
