import logging
# Simplejson prefers str over unicode, looks nicer when printed
import simplejson as json
import pika
import pprint
import sys
import datetime

from contexture.utils import adict, remove_keys, extract_keys, filter_dict_empty
from contexture import __version__

logging.basicConfig()
pp = pprint.PrettyPrinter(indent=1, width=80, depth=None, stream=None)


class CMessage(adict):
    pass


class CObject(CMessage):
    pass


class messages(object):
    '''
    Return a contextmanager/iterator over messages in a queue. The queue is
    dynamically generated and bound using supplied keys and arguments.

    To stop reading, leave the context:

    with messages() as iter:
        for message in iter:
            ...
            if done:
                break

    OR

    with messages() as iter:
        for message in islice(iter, 5):
            process(message)

    OR use it as an iterator and just let it be garbage collected:

    for message in messages():
        process(message)
        if had_enough:
            break
        '''

    def __init__(self,
                 url=None,
                 binding_keys=['#'],
                 binding_args=None,
                 exchange='lc-topic',
                 queue=None,
                 queue_args=None,       # used to declare a queue
                 stdin=None,            # read from a stream instead of a queue
                 raw=False,             # skip json.loads()
                 socket_timeout=None,
                 ):
        if not stdin:
            # Set up us the AMQP
            params = pika.ConnectionParameters()
            if url:
                params = pika.URLParameters(url)
            if socket_timeout:
                params.socket_timeout = socket_timeout
            self.connection = pika.BlockingConnection(params)
            self.channel = self.connection.channel()

            if queue:
                args = queue_args or dict(passive=True)
                self.channel.queue_declare(queue=queue, **args)
                self.queue = queue
            else:
                result = self.channel.queue_declare(
                    arguments={'x-message-ttl': 10 * 60 * 1000},
                    exclusive=True,
                    auto_delete=True
                )
                self.queue = result.method.queue
                for key in binding_keys:
                    self.channel.queue_bind(self.queue,
                                            exchange=exchange,
                                            routing_key=key,
                                            arguments=binding_args)
        self.stdin = stdin
        self.raw = raw

    def __iter__(self):
        if not self.stdin:
            for (method, properties, body) in self.channel.consume(self.queue):
                self.channel.basic_ack(0, multiple=True)
                yield CMessage(headers=properties.headers,
                               rkey=method.routing_key,
                               object=body if self.raw else json.loads(body))
        else:
            for line in self.stdin:
                if not line.strip():
                    continue
                yield adict(json.loads(line))

    def __enter__(self):
        return self.__iter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.__del__()

    def __del__(self):
        if not self.stdin:
            try:
                self.channel.cancel()
                self.connection.close()
            except:
                pass


def strtime(t):
    return datetime.datetime.utcfromtimestamp(t).isoformat() + 'Z'


class objects(messages):
    '''
    Like messages(), but extract collated objects from message stream.
    '''
    def __init__(self,
                 verbose=False,
                 capture_messages=False,
                 yield_messages=False,  # experimental
                 eager=False,           # experimental
                 **kw):
        '''
        verbose: include routing_key and headers
        capture_messages: include the underlying messages
        yield_messages: yield both messages and objects
        eager: yield object *before* it had completed its lifecycle.
        '''
        messages.__init__(self, **kw)
        self.verbose = verbose
        self.capture_messages = capture_messages
        self.eager = eager
        self.yield_messages = yield_messages
        self.db = {}

    def __iter__(self):
        for message in messages.__iter__(self):
            # mobj = json.loads(message.body)
            mobj = message.object
            if 'obj' not in mobj:
                continue
            obj = mobj['obj']
            obj_id = mobj['obj_id']
            collated = self.db.get(obj_id, None)
            status = mobj.get('status', None)
            if not collated:
                # Capture headers/rkey once. Assume they do not change
                # during the live of the object.
                collated = CObject(object=obj,
                                   headers=message.headers,
                                   rkey=message.rkey)
                collated['start'] = strtime(mobj['time_out'])
                if status == 'born':
                    self.db[obj_id] = collated
            else:
                collated['object'].update(obj)
            if self.eager and self.yield_messages:
                # Otherwise you'd have nothing to iterate over.
                # Must yield messages to drive the event loop.
                yield collated if self.verbose else collated['object']
            if self.capture_messages:
                collated.setdefault('messages', []).append(message)
            if self.yield_messages:
                yield message
            if obj_id in self.db and mobj.get('status', None) in ('finished', 'transient'):
                collated['elapsed'] = mobj.get('elapsed', None)
                collated['id'] = obj_id
                collated['end'] = strtime(mobj['time_out'])

                if not (self.eager and self.yield_messages):
                    yield collated if self.verbose else collated['object']
                del self.db[obj_id]


def monitor_cmd():
    import argparse
    parser = argparse.ArgumentParser(description='Simple AMQP monitor, contexture %s' % __version__,
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-H', '--hostname', default='localhost',
                        help='AMQP server hostname')
    parser.add_argument('-u', '--url',
                        help="fully qualified url (overrides hostname)")
    parser.add_argument('-e', '--exchange', default='lc-topic',
                        help='exchange to bind to')
    parser.add_argument('-q', '--queue',
                        help="consume from an existing queue")
    parser.add_argument('-r', '--rkey', default=['#'], nargs='+', help="routing keys")
    parser.add_argument('-a', '--arg', nargs='+',
                        help="binding arguments (key=value pairs)")
    parser.add_argument('-x', '--xmatch', default='all', choices=('all', 'any'),
                        help='x-match')

    parser.add_argument('-s', '--stdin', default=False, action='store_true',
                        help="get input from stdin instead of queue")

    parser.add_argument('-k', '--keys', nargs='+',
                        help='keys to extract (*key for all matches)')
    parser.add_argument('-t', '--trim', nargs='+',
                        help='keys to remove from output')
    parser.add_argument('-c', '--collate', action='count',
                        help='extract collated objects from message stream')
    parser.add_argument('-p', '--pretty', action='store_true', default=False,
                        help='pretty print')
    parser.add_argument('-v', '--verbose', action='count')
    parser.add_argument('-z', action='count', help='trim empty keys/objects')

    args = parser.parse_args()

    if not args.stdin:
        # TODO: add env variable for amqp url
        url = args.url or 'amqp://guest:guest@%s:5672/%%2F' % args.hostname
        binding_args = None
        if args.arg:
            binding_args = {}
            for k, v in (x.split('=') for x in args.arg):
                if v.isdigit():
                    v = int(v)
                binding_args[k] = v
            binding_args['x-match'] = args.xmatch

        print >> sys.stderr, ("Listening for %s/%s on %s on %s" %
                              (args.rkey,
                               binding_args,
                               args.exchange,
                               url))

        stream_args = dict(url=url,
                           binding_keys=args.rkey,
                           binding_args=binding_args,
                           exchange=args.exchange,
                           queue=args.queue)
    else:
        print >> sys.stderr, "Reading from stdin"
        stream_args = dict(stdin=sys.stdin)

    def print_(s):
        if args.pretty:
            pp.pprint(s)
        else:
            print json.dumps(s)

    def post_process(obj):
        if args.trim:
            obj = remove_keys(obj, args.trim)
        if args.z:
            obj = filter_dict_empty(obj)
        return obj

    def on_message(message):
        # (method, properties, body) = message
        out = adict(object=message.object,
                    headers=message.headers,
                    rkey=message.rkey)
        if args.keys:
            out.object = extract_keys(out.object, args.keys)

        out.object = post_process(out.object)

        if not args.verbose:
            out = out.object

        if args.z is None or out:
            print_(out)
            print

    def on_object(obj):
        if args.keys:
            obj = extract_keys(obj, args.keys)

        obj = post_process(obj)

        if args.z is None or obj:
            print_(obj)
            print

    try:
        if args.collate:
            stream_args['verbose'] = args.verbose
            stream, handle = objects, on_object
        else:
            stream, handle = messages, on_message

        stream_iter = stream(**stream_args)
        for item in stream_iter:
            handle(item)
    except KeyboardInterrupt:
        del stream_iter
        print >> sys.stderr, 'Bye.'
