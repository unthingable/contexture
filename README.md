> **contexture** _|kənˈteksˌCHər|_
>
> noun
> * the fact or manner of being woven or linked together to form a connected whole.
> * a mass of things interwoven together; a fabric.
> * the putting together of words and sentences in connected composition; the construction of a text.
> * a connected literary structure; a continuous text.

Contexture is a thin framework for sharing objects' current state across network. This is useful for distributed structured logging, monitoring, data propagation/collection, synchronization and general elevated states of awareness.

Contexture is built on a messaging system (powered by RabbitMQ, see the tail of this document). It solves problems associated with log parsing and directly coupled systems.

<!---
### Why message queues? I can put my object directly into Cassandra/Senty/whatever.

You can, but it tightly couples your system to a given backend. This will make you sad in several ways:

1. Flow control. A slow/downed backend might block your code or lose your messages. At some point you will want to restart just one piece of your pipeline.
1. Modularity: switching to a different consumer likely requires a change to the source.
1. Sharing: adding another consumer also requires a change to the source
1. Serialization:
-->

# Design

Contexture is designed for use in high availability systems. As such, it has the following features:

* low and bounded impact on the running system
* low and bounded propagation delay (a few seconds, depending on configuration)
* high capacity (depending on configuration, as memory allows)
* resistance to problems upstream, such as broker outages

In other words, your change may not propagate instantly but always within a few seconds, and the channel is wide.

The default behavior is to prefer losing messages over blocking or running out of memory
(possible depending on messaging rates and queue size limits), this is configurable.

# Input

Objects go in, objects go out. We can explain that.

There are several ways to get your data into the system. One is to think in terms of contexts. A typical context is a collection of objects associated with a request/event, that you wish to monitor.

Consider a common pattern:

```python
def handle(request):
    # Request is received
    url = request['url']
    start = time.time()

    # Stuff happens
    log.debug('Starting to fetch %s' % url)
    result = requests.get(url)
    log.debug('Status code: %s' % result.status_code)
    status = result.status_code
    if status == 200:
        log.debug('Content: %s' % result.content)

    # And we're done
    log.debug('Finished in %f seconds' % (time.time() - start))
    return result
...
request = {'url': 'http://foo.com'}
result = handle(request)
```

Use Contexture to hold your objects and the above code becomes:

```python
request = {'url': 'http://foo.com'}
with Context(context=request) as ctx:
    result = requests.get(request['url'])
    ctx.status_code = result.status_code
    if ctx.status_code == 200:
        ctx.content = result.content
```

Done. This produces the following messages:

1. object is born, object has one field `url` set to 'http://foo.com'
1. object has a field `status_code` set to XXX
1. object has a field `content` set to YYY
1. object is gone after N seconds

These messages are automatically broadcast to the message bus and, optionally, written to the local logfile. Downstream, you can reconstruct the object or examine its evolution, in realtime.

## Usage & integration

Contexture is designed to be dropped in with minimal impact on the existing ecosystem.

Contexture has several personalities, one of which is `contextmanager`. In most cases it will work without the `with` — the object will properly terminate once it goes out of scope, unless you hold on to a reference. A `with` block is recommended, but you can also `del` the object manually (plus sometimes the object lives beyond the `with` block).

> #### Names and keys
> Once messages are published to the server, they can be selectively routed by consumers using _routing keys_ and _headers_. By default, all messages aggregate into a single stream, routing lets you pick out just your messages.
>
> A routing key is an arbitrary dot-separated alphanumeric string, every message sent by Contexture gets one. Contexture tries to smart about generating default keys by deriving them from current module names and stack traces. When unsure, use `name` or `routing_key` argument when constructing a Contexture instance.
>
> You can see the default name that LC picked by casting it to `str`.
>

### Direct

Create a new object whenever you need a context.

```python
def handle(request):                    # Outgoing messages (approximately):
    ctx = Context()                     # {status: 'born', obj: {}}
    ctx.request = request               # {obj: {request: <request>}}
    ...
    result = process_request(request)
    ctx.result = result                 # {obj: {result: <result>}}
    return                              # {status: 'finished', elapsed: 0.1234}
```

You may also preload an existing context dict by passing a `context` argument to the initializer.

```python
Context(context={'a': 1, 'foo': 'bar'})  # {status: 'born', obj: {a: 1, foo: 'bar'}}
```

#### Reserved keywords and direct access
Because Contexture is not a real dict but a thing of magic, some attribute names cannot be used for direct access (*_*, *context*, *log*, *update*). For example, you cannot do

```python
ctx.log = 'something'
print ctx.log
```

Do it by accessing the context dict directly:

```python
ctx.update(log='something')
print ctx.context['log']
```

Note the use of `ctx.update()` instead of `ctx.context.update()`. Don't worry about accidentally using a reserved keyword, Contexture will not let you.

### Subclass

You can sublass Context. It will try to derive a name/routing_key from the name of your new class.

### Object proxy

You have an existing object that you want to monitor and do not want to reimplement it as a subclass of LC. No problem, wrap it:

```python
class MyObj(object):
    x = 1

    @property
    def y(self):
        return 2

    def f(self):
        return 3

myobject = MyObj()
original_object = myobject

myobject = Context(obj=myobject)
myobject.f() == 3                       # True
myobject.y == 2                         # True
myobject.x == 1                         # True

myobject.y = 10                         # works! y is now part of context, shadowing the original
myobject.y == 10                        # True
original_object.y == 2                  # True

myobject.x = 111
myobject.x == original_object.x == 1    # True, as expected
```

This wrapped object behaves like the original object (function calls, @properties, etc.), but it is also a context: it will capture all attribute assignments and allow creation of new attributes (shadowing the existing read-only ones).

In other words, wrap an existing object in Contexture and it will do its best to make sure neither the object nor the code that is using it notice a difference.

<!--- rewrite maybe? -->

### Exclusions

You have a complex dict but you only care to broadcast a part of it. Add the private bits to `ignore` and it will not be reported.

```python
mydict = dict(x=1, y=2, privatestuff=whatever)
ctx = Context(context=mydict,
              ignore=['privatestuff', 'foo'])   # obj: {x: 1, y: 2}
ctx.x = 5                                       # obj: {x: 5}
ctx.foo = 1234                                  # nothing
```

### Actually logging to the message bus

It slices, it dices, it logs! You can still use it as a conventional logger, via the `log` attribute.

```python
ctx.log.info('OHAI')
```

Use the context to format your messages

```python
ctx = Context(context={'foo': 1})                # obj: {foo: 1}
ctx.bar = 2                                         # obj: {bar: 2}
...
ctx.log.debug('my foo is {foo} and my bar is {bar}')    # obj:{}, message: 'my foo is 1 and my bar is 2'
```

### Logging to a logfile

Provide your own logger instance and Contexture will log context changes to a log file for you, automatically:

```python
ctx = Context(logger=logging.getLogger(__name__))    # <name> <id>: status = born
ctx.update(x=1, y=2)                                 # <name> <id>: x = 1, y = 2
```

Note that this will work even without an AMQP handler configured.

## Usage notes

Data must be JSON serializeable.

### pika.exceptions.AMQPConnectionError

This means the backend could not connect to the broker. This harms nothing, only means your messages won't make it upstream. See below.

### Will this break my code if X happens downstream?

No.

Inside the handler, your messages are buffered in a queue and picked up by a publisher thread every second. If the publisher cannot publish to the RabbitMQ server, it will stop publishing, the queue will fill up and the new messages will be discarded. The backend will keep trying to reconnect and things will return to normal once it does.

This means Contexture can survive some broker downtime with no loss of traffic. How long — depends on your message rates and the size of the queue (currently 5000 but we can make this configurable).

### Clean exit

It is possible to ensure the context transmits all of its messages before the process exits. Declare your context with ``wait=True`` and it will block on exit until the publish queue is empty.

The old way was to call `time.sleep(2)` before exiting your program, that still works.

### Unicode headers

Pika does not like your unicode headers. If using `unicode_literals`, be sure to do something like:

```python
Context(headers={b'myheader': b'something'})
```

### Packing & sequencing

When updating multiple fields, you have a choice of how the updates will be packed
on the messages stream. For example, this will create 3 separate messages:

    ctx.foo = 1
    ctx.bar = 2
    ctx.baz = 5

and this only one:

    ctx.update(foo=1, bar=2, baz=5)

The spreading of the updates exposes more of the internal behavior and invidivual timing.
When not needed, it is preferable to pack multiple udpates into one.

Same goes for preloading contexts during initialization.

### Transient objects

Normally the context object announces its birth and death. You can bypass that and send your object upstream in the most minimalist way:

```python
def push(obj):
    'Convenience function for publishing a short-lived object'
    Context(name='my.routing.key', transient=True, context=obj)
...
myobject = dict(foo='whatever', ...)
...
push(myobject)
```

### Long lived objects

The other extreme. You can think of a long lived object as a simple streaming database handle. That is, you ignore the object's own lifetime and treat it as a delta emitter, while listening for those deltas on the other end.

```python
db = Context(name='faux_db')
db.mystatus = 'now this'
...
db.mystatus = 'and now that'
```

And on the other end you might do (see the section on _lcmon_ below).

    $ lcmon -v -r faux_db -k obj
    {"mystatus": "now this"}
    {"mystatus": "and now that"}

### Objects with custom IDs

```python
ctx = Context(guid='1234')
```

Context objects are assigned UUIDs automatically, but you can provide your own. This may be helpful with transient objects in particular.

## Configuration

Put this in your config:

```
[logger_contexture]
level=DEBUG
handlers=AMQPHandler
qualname=contexture
propagate=0

[handler_AMQPHandler]
class=contexture.backend.amqp_handler.AMQPHandler
level=DEBUG
args=("amqp://guest:guest@localhost:5672/%2F", "lc-topic", "topic")
```

Add the logger to loggers and handler to handlers (see `contexture/config.conf` for an example). The arguments to AMQP handler are:

1. AMQP connection string
1. Exchange to which to publish (will be created as needed)
1. Exchange type
1. (optional) A dict of headers to be included with every message

# Output

So you know everything (almost) about getting data onto the message bus. Now what?

Inspect the messages as they fly by or grab them from the stream for your own devilish purpose.

## Monitoring: lcmon

Included in _contexture_ package is a handy monitoring utility.

    $ lcmon -h
    usage: lcmon [-h] [-r RKEYS] [-a ARGS [ARGS ...]] [-x {all,any}] [-e EXCHANGE]
                 [-H HOSTNAME] [-u URL] [-q QUEUE] [-s] [-k KEYS [KEYS ...]] [-c]
                 [-p] [-v]

    Simple AMQP monitor

    optional arguments:
      -h, --help            show this help message and exit
      -H HOSTNAME, --hostname HOSTNAME
                            AMQP server hostname (default: localhost)
      -u URL, --url URL     fully qualified url (overrides hostname) (default:
                            None)
      -e EXCHANGE, --exchange EXCHANGE
                            exchange to bind to (default: lc-topic)
      -q QUEUE, --queue QUEUE
                            consume from an existing queue (default: None)
      -r RKEY [RKEY ...], --rkey RKEY [RKEY ...]
                            routing keys (default: ['#'])
      -a ARG [ARG ...], --arg ARG [ARG ...]
                            binding arguments (key=value pairs) (default: None)
      -x {all,any}, --xmatch {all,any}
                            x-match (default: all)
      -s, --stdin           get input from stdin instead of queue (default: False)
      -k KEYS [KEYS ...], --keys KEYS [KEYS ...]
                            keys to extract (*key for all matches) (default: None)
      -c, --collate         extract collated objects from message stream (default:
                            None)
      -p, --pretty          pretty print (default: False)
      -v, --verbose

This will print traffic on the message bus in realtime, until terminated.

### -H, --hostname

By default _lcmon_ connects to localhost. Open an SSH tunnel (port 5672) or provide the hosname explicitly:

    $ lcmon -H <amqp server host>

This will expand to a default URL of `amqp://guest:guest@<hostname>:5672/%2F`. Alternatively you can use `-U` to provide the full URL.

### -q, --queue

Consume from an existing queue.

By default, _lcmon_ creates an anonymous queue which disappears after the connection is closed (this happens _almost_ always). You can declare a more permanent queue and have messages survive _lcmon_ and even broker restarts.

**Warning!** Take care to not consume from queues not belonging to you. This is a destructive operation.

### -r, --rkeys

One or more routing keys or wildcards to filter on. Wildcards will only work with topic exchanges.

### Binding args (-a)

Arguments for use with headers exchange. Use with `-x`.

### -s, --stdin

You can store the output in a file, then read it back in and reprocess with options `-c`, `-k`, `-v` and `-p`. This is useful for temporary local storage (`-v` is important here):

    $ lcmon -v > myfile
    ^C
    $ lcmon -sc < myfile

### -k, --keys

Extract occurences of keys from the object.

Objects can be big, and you might be interested only in a subset of keys. Here is a real message:

    {"status": "finished", "obj": {"elapsed": 2.7338700294494629}, "id": "c529c182-62b8-49db-a0aa-2ba4cc991af2", "handler_id": "76bb5a4e-34b7-43a0-8ffc-19e448d33ea0", "elapsed": 1.1670801639556885, "queue": 0, "time_in": 1360720859.8556099, "time_out": 1360720861.0226901}

Suppose you only care about elapsed times. Running `lcmon -k elapsed` prints this:

    {'elapsed': 1.1670801639556885}

Notice there are actually two `elapsed` fields in the message. By default, `-k` prints the first one found by breadth-first search. Prefixing the name of the key with `*` gets all of them:

    In [6]: monitor.extract_keys(obj, ['elapsed'])
    Out[6]: {'elapsed': 1.1670801639556885}

    In [7]: monitor.extract_keys(obj, ['*elapsed'])
    Out[7]: {'elapsed': (1.1670801639556885, 2.733870029449463)}

### -c, --collate

Reconstruct complete context objects from the stream, so instead of a sequence like

    status: 'born', obj: {}
    obj: {x: 1, y: 2}
    obj: {x: 5}
    status: 'finished'

you will see the object

    {x: 5, y: 2}

This only works if the object terminates properly, and is not useful with long-lived objects. It does work with transient objects.

Note `-k` option works on collated objects as well.

### -v

Include the headers and routing key in the final object, resulting in a slightly different structure. You will want this often (hint: grep).

## Consuming: messages and objects

The easiest part.

```python
from contexture.monitor import messages, objects

for message in monitor.messages(binding_keys=['#']):
    outer_obj = message['object']
    my_obj = outer_obj['obj']
    my_id = outer_obj['id']
```

The heart of _lcmon_, `monitor` module provides two important functions: `messages` and `objects`. They return iterators over messages and collated objects. The iterators are also _contextmanagers_, so you can do:

```python
with messages() as m_iter:
    for message in m_iter:
        dostuff()
```

They take same arguments as `lcmon`, see `monitor.py` for details. Again, when using a named queue, remember to delete it when done (`message.channel.queue_delete(<name>)` works, see below).

A full example with objects. This also demonstrates publishing:

```python
objects = monitor.objects(verbose=True, capture_messages=True, queue='analytics.es')
channel = objects.channel

print 'Pushing objects to ElasticSearch River'
buffer_.clear()
for obj in objects:
    buffer_.append({'index': dict(_ttl='7d',
                                   _index='lc',
                                   _type=obj.pop('rkey'),
                                   _id=obj.pop('id'),
                    )})
    buffer_.append(obj)
    channel.basic_publish('elasticsearch',
                          'elasticsearch',
                          '\n'.join(map(json.dumps, buffer_)) + '\n')
```

### Queue safety

* Q: What if I don't consume my messages fast enough?
* A: You laggard!

But don't worry, RabbitMQ has tolerance for the likes of you. By default, Contexture declares all queues with a TTL (usually 60 seconds) — messages left unconsumed longer than that are automatically sent to /dev/null, providing a bound on queue growth. So even if your consumer gets terminally stuck, the world will go on.

# Storage

Left as an exercise.

# Miscellanea

What's in the box:
* an ActiveRecord-style data container (`Context`), for exposing your crazy world to the backend
* an AMQP backend handler, for marshalling updates to the message bus
* utilities for monitoring the message bus (lcmon)
Contexture helps you remotely monitor and analyze your code, in realtime, as it runs on one or more machines across a network. More backends can be added with relative ease.


Design considerations include:

* Easy integration: minimal effort is required to start sending and receiving context objects.
* Zero impact: LC is guaranteed to not impact the rest of the system. It is
asyncronous and handles downstream failures gracefully. Worst
that it will do is a little memory usage (= size of the internal queue) and loss of updates
(once the queue fills up).


### RabbitMQ

The default backend is RabbitMQ. Things to know about AMQP:

* The server is a __broker__.
* __Routing key__ and __headers__ are assigned to the message by the publisher and are used by the
broker to route the message.
* __Exchange__ is where the published message arrives first.
* The consumer gets its messages from a __queue__. To start receiving messages the consumer must
first declare a queue. Queues are often dynamic and disposable, but can be made permanent.
* __Binding__ routes messages from exchange to queue. Bindings can use routing keys
and/or headers to filter messages.

----

## What's wrong with direct coupling?

1. Producer -> consumer dependency: the consumer must be up and runnning, and be able to consume messages fast enough.
1. Producer <- consumer dependency: the producer is responsible for knowing how to talk to the consumer and for maintaining an open channel.
1. Ccomplex systems and intercepting streams: adding multiple consumers and/or producers is a challenge, as is reloading individual components in long running processes.

These problems can be addressed by implementing plumbing in all of your components or by using a buffered message queue to connect them.

## blah

* how is this better than syslog?
    1. updates assemble back into objects
    2. context objects are linkable

## Congratulations

You have read the whole thing.
