from itertools import chain, islice
import json
import pika
import pprint

pp = pprint.PrettyPrinter(indent=1, width=80, depth=None, stream=None)


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


def monitor(url=None, args=None, keys=['#'], exchange='lc-topic',
            verbose=False, mapkeys=None, pretty=False):
    "Listen to AMQP and print results"

    def on_message(channel, method_frame, header_frame, body):
        if verbose:
            print method_frame.delivery_tag, method_frame, header_frame
        if not mapkeys:
            if not pretty:
                print body
            else:
                pp.pprint(json.loads(body))
            print
        else:
            extracted = extract_keys(json.loads(body), mapkeys)
            if pretty:
                pp.pprint(extracted)
            else:
                print extracted
            print
        # channel.basic_ack(delivery_tag=method_frame.delivery_tag)

    params = None
    if url:
        params = pika.URLParameters(url)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()

    result = channel.queue_declare(auto_delete=True,
                                   arguments={'x-message-ttl': 60000}
                                   )
    queue = result.method.queue
    for key in keys:
        channel.queue_bind(queue,
                           exchange=exchange,
                           routing_key=key,
                           arguments=args)
    channel.basic_consume(on_message, queue, no_ack=True)
    try:
        print "Listening for %s/%s on %s on %s" % (keys, args, exchange, url)
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
    connection.close()


def monitor_cmd():
    import argparse
    parser = argparse.ArgumentParser(description='Simple AMQP monitor',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-k', '--keys', default='#', help="binding keys")
    parser.add_argument('-a', '--args', nargs='+',
                        help="binding arguments (key=value pairs)")
    parser.add_argument('-e', '--exchange', default='lc-topic',
                        help='exchange to bind to')
    parser.add_argument('-H', '--hostname', default='localhost',
                        help='AMQP server hostname')
    parser.add_argument('-u', '--url',
                        help="Fully qualified url (overrides hostname)")
    parser.add_argument('-m', '--map', nargs='+',
                        help='keys to extract (*key for all matches)')
    parser.add_argument('-p', '--pretty', action='store_true', default=False,
                        help='pretty print')
    parser.add_argument('-v', '--verbose', action='count')

    args = parser.parse_args()
    url = args.url or 'amqp://guest:guest@%s:5672/%%2F' % args.hostname
    binding_args = None
    if args.args:
        binding_args = dict(x.split('=') for x in args.args.split())

    monitor(keys=args.keys.split(),
            args=binding_args,
            exchange=args.exchange,
            url=url,
            mapkeys=args.map,
            verbose=args.verbose,
            pretty=args.pretty)
