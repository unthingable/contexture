import inspect
import logging
import logging.config
import os.path
from pkg_resources import resource_filename
from time import time
import uuid
import weakref

from . import backend

'''
Use case:

ctx = Context(name="mycontext")
ctx.foo = 1
ctx.update(msg="i has {foo} and {bar}",
           level=logging.DEBUG,
           bar='bar')
x ctx.log.info("for great %s", "justice")
...

with Context(context=dict(foo=1)) as ctx:
    ...
    ctx.foo = 3
'''

# TODO: add termination protection, add test for handler queue join

backend_logger = None
backend_handler = None


config = {
    'wait': False
}


# primitive config prototype
def configure(backend=backend.amqp.AMQPHandler,
              # args=("amqp://guest:guest@localhost:5672/%2F", "lc-topic", "topic"),
              args=[],
              kwargs={}):
    '''
    Explicitly configure contexture with a handler.

    This will skip the logging-based configuration.
    '''
    global backend_handler
    backend_handler = backend(*args, **kwargs)
    config.update({k: v for k, v in kwargs.iteritems() if k in config})


def _safe_logger():
    '''
    Return a logger if logging has been genuinely configured for Contexture
    (via an educated guess).
    '''
    l1 = logging.getLogger('asdfoiuqwerzxcv')
    l2 = logging.getLogger("contexture")
    if l1.__class__ == logging.Logger and l2.__class__ != logging.Logger:
        return l2

backend_logger = _safe_logger()
if backend_logger:
    # test this!
    backend_handler = backend_logger.handlers[0]


class _dummy_obj:
    pass


def push_to_backend(obj, level=None):
    if not backend_logger:
        if not backend_handler:
            print 'Logging not configured (or hijacked), calling default configure()'
            configure()
        backend_handler.emit_obj(obj)
    else:
        # global backend_logger
        # if not backend_logger.handlers:
        #         # Load config and rebuild
        #         # Because this is deferred, this will undo any logger hijacking (HI, CELERY!).
        #         print 'Initializing default contexture logger'
        #         config_file = resource_filename(__name__, 'config.conf')
        #         config_file = os.path.normpath(config_file)
        #         logging.config.fileConfig(config_file)
        #         backend_logger = logging.getLogger("contexture")
        backend_logger.log(level, obj)


# to be used by itself _and_ extended
class Context(object):
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
                 # Common configuration
                 name=None,         # amqp routing key
                 routing_key=None,  # leave empty to use name
                 headers={},        # amqp headers
                 context={},        # initial context
                 ignore=[],         # exclude from handling
                 logger=None,       # custom logger
                 guid=None,         # provide your own ID

                 # Behavior
                 obj=None,          # native object to wrap
                 silent=False,      # for using LC from SH
                 transient=False,   # transient object
                 wait=None,         # for handler queue to empty (t/f/none)
                                    # (None uses configuration, t/f overrides)

                 on_exit=None,      # exit callback
                 ):
        self.context = {}
        self._ = _dummy_obj()
        self._.headers = headers
        self._.silent = silent
        self._.guid = guid or str(uuid.uuid4())
        self._.ignore = tuple(ignore)
        self._.deleted = False
        self._.transient = transient
        self._.wait = wait if wait is not None else config['wait']

        # An object reference for extended accessors
        if obj:
            self._.obj = obj
            self._.headers['via'] = '%s.%s' % (obj.__class__.__module__,
                                               obj.__class__.__name__)
        # Some contention below: do we specify wrapped object
        # explicitly or allow more magic by treating <context> as obj?

        # elif context:
        #     # Context could be a subclassed dict with property
        #     # methods, who knows.
        #     self._.obj = context
        # -- No, specify obj explicitly if you need it.
        else:
            self._.obj = None

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

        status = transient and 'transient' or 'born'
        self._update(meta=dict(status=status), context=context)

    def _update(self, msg=[], level=logging.DEBUG, context={}, meta={}, format=True):
        '''
        Logger-like behavior
        '''
        self.context.update(context)
        obj = {}
        for k, v in context.iteritems():
            if k in self._.ignore:
                continue
            if isinstance(v, Context):
                v = v._.guid
            obj[k] = v

        if not msg and not (obj or meta):
            return

        if msg:
            if len(msg) > 1:
                msg = msg[0] % msg[1:]
            else:
                msg = msg[0]
            if format:
                try:
                    msg = msg.format(**self.context)
                except Exception, e:
                    pass
        else:
            msg = None

        # send through backend
        if not self._.silent:
            out_obj = {'obj_id': self._.guid,
                       'obj': obj,
                       'routing_key': self._.routing_key,
                       'headers': self._.headers}
            if msg:
                out_obj['message'] = msg
            # Careful, don't clobber
            out_obj.update(meta)
            push_to_backend(out_obj, level=level)

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
        if hasattr(Context, name):
            if getattr(self, name) is None:
                object.__setattr__(self, name, value)
            else:
                raise AttributeError("Attribute '%s' is reserved"
                                     " (use update())" % name)
        else:
            # TODO: add a test for this
            if self._.obj:
                try:
                    setattr(self._.obj, name, value)
                except Exception, e:
                    if self._.log:
                        self._.log.exception(e)

            self.update(**{name: value})

    def __getattr__(self, name):
        if not hasattr(self, 'context'):
            raise Exception("Context not initialized, call __init__()!")
        if name not in self.context:
            if self._.obj and hasattr(self._.obj, name):
                return getattr(self._.obj, name)
            raise AttributeError
        return self.context[name]

    def __str__(self):
        return "%s %s" % (self._.name, self._.guid)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.__del__()

    def __del__(self):
        if self._ and not self._.deleted and not self._.transient:
            # Calling self.update will resurrect us in the middle
            # of dying, causing a loop of death. So, only die once.
            self._.deleted = True
            self._update(meta=dict(status="finished",
                                   elapsed=(time() - self._.created_at)))
            if self._.wait:
                backend_handler._queue.join()
