import stomp


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
    pass
