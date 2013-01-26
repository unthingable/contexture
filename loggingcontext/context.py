import inspect
import logging
import logging.config
import os.path
from pkg_resources import resource_filename
from time import time
import uuid
import weakref

'''
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

backend_logger = logging.getLogger("loggingcontext")

# See if we're properly configured
if not backend_logger.handlers:
    # Load config and rebuild
    config_file = resource_filename(__name__, 'config.conf')
    config_file = os.path.normpath(config_file)
    logging.config.fileConfig(config_file)
    backend_logger = logging.getLogger("loggingcontext")

# to be used by itself _and_ extended
class LoggingContext(object):
    '''
    Reserved members:
        context
        log
        update
    '''

    # Reserved members to be enforced by __setattr__:
    context = None
    log = None
    _ = None    # for keeping stuff out of main namespace

    class LogProxy(object):
        def __init__(self, ctx):
            self.ctx_ref = weakref.ref(ctx)

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
                return lp.ctx_ref()._update(msg=msg, level=level, context=kw)
            log_func.func_name = name
            return log_func

        setattr(LogProxy, level_name, closure(level, level_name))

    def __init__(self,
                 name=None,         # amqp routing key
                 routing_key=None,  # leave empty to use name
                 headers={},        # amqp headers
                 context={},        # initial context
                 ignore=[],         # exclude from handling
                 silent=False,      # for using LC from SH
                 logger=None,       # custom logger
                 ):
        self.context = {}
        self._ = _dummy_obj()
        self._.headers = {}
        self._.silent = silent
        self._.guid = str(uuid.uuid4())
        self._.ignore = tuple(ignore)
        self._.deleted = False

        # Unnamed contexts: attempt to get a meaningful name
        if name is None:
            mname = ''
            frame = inspect.stack()[1]
            obj = frame[0]
            clazz = obj.f_locals.get('self', None)
            module = inspect.getmodule(obj)
            if clazz:
                mname = '%s.%s' % (clazz.__class__.__module__,
                                   clazz.__class__.__name__)
            elif module:
                mname = module.__name__
            elif not frame[3].startswith('<'):
                mname = frame[3]

            name = self.__class__.__name__
            if mname:
                name = '.'.join((mname, name))

        self._.name = name
        self._.routing_key = name if routing_key is None else routing_key
        self._.created_at = time()
        self._.log = logger

        # Construct the log proxy
        self.log = self.LogProxy(self)

        self.update(status="born", **context)

    def _update(self, msg=[], level=logging.DEBUG, context={}):
        self.context.update(context)
        obj = dict((k, v) for k, v in context.iteritems()
                   if k not in self._.ignore)

        if not msg and not obj:
            return

        if msg:
            if len(msg):
                msg = msg[0] % msg[1:]
            else:
                msg = msg[0]
            msg = msg.format(**self.context)
        else:
            msg = None
        if msg:
            obj['message'] = msg

        # send through backend
        if not self._.silent:
            out_obj = {'obj_id': self._.guid,
                       'obj': obj,
                       'routing_key': self._.routing_key}
            backend_logger.log(level, out_obj)

        # Log log
        if self._.log and self._.log.isEnabledFor(level):
            kwstr = ', '.join("%s = %s" % x for x in context.iteritems())
            msg = '; '.join(x for x in (msg, kwstr) if x)
            self._.log.log(level, '%s: %s', self._.guid, msg)

    def update(self, **kw):
        '''
        Useful when you don't care about messages or log levels.
        '''
        return self._update(context=kw)

    def __setattr__(self, name, value):
        if hasattr(LoggingContext, name):
            if getattr(self, name) is None:
                object.__setattr__(self, name, value)
            else:
                raise AttributeError("Attribute '%s' is reserved"
                                     " (use update())" % name)
        else:
            self.update(**{name: value})

    def __getattr__(self, name):
        if not hasattr(self, 'context'):
            raise Exception("LoggingContext not initialized, call __init__()!")
        if name not in self.context:
            raise AttributeError
        return self.context[name]

    def __str__(self):
        return "%s %s" % (self._.name, self._.guid)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.__del__()

    def __del__(self):
        if self._ and not self._.deleted:
            # Calling self.update will resurrect us in the middle
            # of dying, causing a loop of death. So, only die once.
            self._.deleted = True
            self.update(elapsed=(time() - self._.created_at),
                        status="finished")
