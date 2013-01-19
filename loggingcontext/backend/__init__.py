import stomp
import json
import logging
import stomp_handler

from loggingcontext.settings import config

log = logging.getLogger(__name__)

handlers = []

# load handlers, start threads
for name, h_config in config.iteritems():
    if not name.endswith('_handler'):
        continue
    module = __import__(name, globals(), locals())
    handlers.extend(module.configure_handlers())


def collate(stream):
    '''
    Given (context, dict) pairs, assemble the object incrementally.
    Return context->object dict.
    '''
    db = {}
    for ctx, increment in stream:
        obj = db.setdefault(ctx, {})
        obj.update(increment)
    return db


def emit(ctx, obj):
    for handler in handlers:
        handler(ctx, obj)
