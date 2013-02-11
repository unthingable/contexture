from collections import namedtuple
from itertools import chain, islice
# Simplejson prefers str over unicode, looks nicer when printed
import simplejson as json
import pika
import pprint


pp = pprint.PrettyPrinter(indent=1, width=80, depth=None, stream=None)


# Place this here for now... This likely should go with other
# AMQP stuff, like the handler, but we'll decide later.

Message = namedtuple('Message', 'method properties body')


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
                 ):

        # Set us up the AMQP
        params = None
        if url:
            params = pika.URLParameters(url)
        self.connection = pika.BlockingConnection(params)
        self.channel = self.connection.channel()

        result = self.channel.queue_declare(auto_delete=True,
                                            arguments={'x-message-ttl': 60000}
                                            )
        self.queue = result.method.queue
        for key in binding_keys:
            self.channel.queue_bind(self.queue,
                                    exchange=exchange,
                                    routing_key=key,
                                    arguments=binding_args)

    def __iter__(self):
        for (method, properties, body) in self.channel.consume(self.queue):
            yield Message(method, properties, body)
            self.channel.basic_ack(method.delivery_tag)

    def __enter__(self):
        return self.__iter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.__del__()

    def __del__(self):
        try:
            self.channel.cancel()
            self.connection.close()
        except:
            pass


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
            mobj = json.loads(message.body)
            if 'obj' not in mobj:
                continue
            obj = mobj['obj']
            obj_id = mobj['obj_id']
            collated = self.db.get(obj_id, None)
            if not collated:
                # Capture headers/rkey once. Assume they do not change
                # during the live of the object.
                collated = dict(object=obj,
                                headers=message.properties.headers,
                                rkey=message.method.routing_key)
                self.db[obj_id] = collated
            else:
                collated['object'].update(obj)
            if 'finished' == mobj.get('status', None):
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
                        help="Fully qualified url (overrides hostname)")
    parser.add_argument('-k', '--keys', nargs='+',
                        help='keys to extract (*key for all matches)')
    parser.add_argument('-c', '--collate', action='count',
                        help='extract collated objects from message stream')
    parser.add_argument('-p', '--pretty', action='store_true', default=False,
                        help='pretty print')
    parser.add_argument('-v', '--verbose', action='count')

    args = parser.parse_args()

    url = args.url or 'amqp://guest:guest@%s:5672/%%2F' % args.hostname
    binding_args = None
    if args.args:
        binding_args = {}
        for k, v in (x.split('=') for x in args.args):
            if v.isdigit():
                v = int(v)
            binding_args[k] = v
        binding_args['x-match'] = args.xmatch

    print "Listening for %s/%s on %s on %s" % (args.rkeys,
                                               binding_args,
                                               args.exchange,
                                               url)

    def print_(s):
        if args.pretty:
            pp.pprint(s)
        else:
            print s

    def on_message(message):
        (method, properties, body) = message
        if args.verbose:
            print method.delivery_tag, method, properties
        if not args.keys:
            if not args.pretty:
                print body
            else:
                pp.pprint(json.loads(body))
            print
        else:
            extracted = extract_keys(json.loads(body), args.keys)
            print_(extracted)
            print

    def on_object(obj):
        if args.keys:
            obj = extract_keys(obj, args.keys)
        print_(obj)
        print

    stream_args = dict(url=url,
                       binding_keys=args.rkeys,
                       binding_args=binding_args,
                       exchange=args.exchange)

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
