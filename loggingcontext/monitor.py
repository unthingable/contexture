from collections import namedtuple
from itertools import chain, islice
import logging
# Simplejson prefers str over unicode, looks nicer when printed
import simplejson as json
import pika
import pprint
import sys
import time


logging.basicConfig()
pp = pprint.PrettyPrinter(indent=1, width=80, depth=None, stream=None)


# Place this here for now... This likely should go with other
# AMQP stuff, like the handler, but we'll decide later.

Message = namedtuple('Message', 'method properties body')


class adict(dict):
    def __init__(self, *args, **kwargs):
        super(adict, self).__init__(*args, **kwargs)
        self.__dict__ = self


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
                 stdin=False,
                 ):
        if not stdin:
            # Set up us the AMQP
            params = None
            if url:
                params = pika.URLParameters(url)
            self.connection = pika.BlockingConnection(params)
            self.channel = self.connection.channel()

            qargs = dict(queue=queue) if queue else dict(auto_delete=True)
            result = self.channel.queue_declare(arguments={'x-message-ttl': 10 * 60 * 1000},
                                                exclusive=True,
                                                **qargs
                                                )
            self.queue = result.method.queue
            for key in binding_keys:
                self.channel.queue_bind(self.queue,
                                        exchange=exchange,
                                        routing_key=key,
                                        arguments=binding_args)
        self.stdin = stdin

    def __iter__(self):
        if not self.stdin:
            for (method, properties, body) in self.channel.consume(self.queue):
                self.channel.basic_ack(0, multiple=True)
                yield adict(headers=properties.headers,
                            rkey=method.routing_key,
                            object=json.loads(body))
        else:
            for line in sys.stdin:
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
    return time.strftime('%F %H:%M:%S', time.localtime(int(t)))


class objects(messages):
    '''
    Like messages(), but extract collated objects from message stream.
    '''
    def __init__(self, verbose=False, **kw):
        messages.__init__(self, **kw)
        self.verbose = verbose
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
            if not collated:
                # Capture headers/rkey once. Assume they do not change
                # during the live of the object.
                collated = dict(object=obj,
                                headers=message.headers,
                                rkey=message.rkey)
                self.db[obj_id] = collated
                collated['start'] = strtime(mobj['time_out'])
            else:
                collated['object'].update(obj)
            if 'finished' == mobj.get('status', None):
                collated['elapsed'] = mobj.get('elapsed', None)
                collated['id'] = obj_id
                collated['end'] = strtime(mobj['time_out'])

                yield collated if self.verbose else collated['object']
                del self.db[obj_id]


def findkey(d, key):
    "Find all occurrences of <key> in dict <d> and its contents"
    if isinstance(d, dict):
        if key in d:
            result = d[key]
            if isinstance(d, (tuple, list)):
                for item in result:
                    yield item
            else:
                yield result
        for item in findkey(d.values(), key):
            yield item
    elif isinstance(d, (tuple, list)):
        for item in chain(*(findkey(x, key) for x in d)):
            yield item


def extract_keys(d, keys):
    '''
    Given a list of keys, do findkey(), expand single element lists
    and return a dict.
    '''
    result = {}
    for key in keys:
        if key.startswith('*'):
            key = key.lstrip('*')
            result[key] = tuple(findkey(d, key))
        else:
            result[key] = tuple(islice(findkey(d, key), 1))
        if len(result[key]) == 1:
            result[key] = result[key][0]
    return result


def monitor_cmd():
    import argparse
    parser = argparse.ArgumentParser(description='Simple AMQP monitor',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-r', '--rkeys', default='#', help="routing keys")
    parser.add_argument('-a', '--args', nargs='+',
                        help="binding arguments (key=value pairs)")
    parser.add_argument('-x', '--xmatch', default='all', choices=('all', 'any'),
                        help='x-match')
    parser.add_argument('-e', '--exchange', default='lc-topic',
                        help='exchange to bind to')
    parser.add_argument('-H', '--hostname', default='localhost',
                        help='AMQP server hostname')
    parser.add_argument('-u', '--url',
                        help="fully qualified url (overrides hostname)")
    parser.add_argument('-q', '--queue',
                        help="create a non-transient queue")

    parser.add_argument('-s', '--stdin', default=False, action='store_true',
                        help="get input from stdin instead of queue")

    parser.add_argument('-k', '--keys', nargs='+',
                        help='keys to extract (*key for all matches)')
    parser.add_argument('-c', '--collate', action='count',
                        help='extract collated objects from message stream')
    parser.add_argument('-p', '--pretty', action='store_true', default=False,
                        help='pretty print')
    parser.add_argument('-v', '--verbose', action='count')

    args = parser.parse_args()

    if not args.stdin:
        url = args.url or 'amqp://guest:guest@%s:5672/%%2F' % args.hostname
        binding_args = None
        if args.args:
            binding_args = {}
            for k, v in (x.split('=') for x in args.args):
                if v.isdigit():
                    v = int(v)
                binding_args[k] = v
            binding_args['x-match'] = args.xmatch

        print >> sys.stderr, ("Listening for %s/%s on %s on %s" %
                              (args.rkeys,
                               binding_args,
                               args.exchange,
                               url))

        stream_args = dict(url=url,
                           binding_keys=args.rkeys,
                           binding_args=binding_args,
                           exchange=args.exchange,
                           queue=args.queue)
    else:
        print >> sys.stderr, "Reading from stdin"
        stream_args = dict(stdin=True)

    def print_(s):
        if args.pretty:
            pp.pprint(s)
        else:
            print json.dumps(s)

    def on_message(message):
        # (method, properties, body) = message
        out = adict(object=message.object,
                    headers=message.headers,
                    rkey=message.rkey)
        if args.keys:
            out.object = extract_keys(out.object, args.keys)
        if not args.verbose:
            out = out.object

        print_(out)
        print

    def on_object(obj):
        if args.keys:
            obj = extract_keys(obj, args.keys)
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
