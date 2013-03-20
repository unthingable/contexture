'''
Measure error rates and open ongoing requests.

A primitive gunicornable web server.
'''

from collections import Counter, deque, defaultdict
from itertools import islice
import simplejson as json
from operator import itemgetter
import threading
import time
from urlparse import parse_qs

from contexture import monitor

running_errors = Counter()
running_requests = Counter()
errors = defaultdict(deque)
requests = defaultdict(deque)
snaplock = threading.Lock()


def counter():
    for message in monitor.messages(binding_keys=['#'],
                                    queue='analytics.errorcount'):
        snaplock.acquire()
        if 'item_id' in message['headers']:
            obj = message['object']
            item_id = message['headers']['item_id']
            if obj.get('status', '') == 'born':
                running_requests[item_id] += 1
            elif obj.get('status', '') == 'finished':
                if running_requests[item_id] > 0:
                    running_requests[item_id] -= 1
            if 'error' in str(message):
                running_errors[item_id] += 1
        snaplock.release()


def snapshot():
    snaplock.acquire()
    item_ids = set(errors.keys())
    item_ids.update(running_requests.keys())
    for mid in item_ids:
        eq = errors[mid]
        rq = requests[mid]
        eq.appendleft(running_errors[mid])
        rq.appendleft(running_requests[mid])
        while len(eq) > 60:
            eq.pop()
        while len(rq) > 60:
            rq.pop()
    running_errors.clear()
    snaplock.release()


def snappy():
    while True:
        snapshot()
        time.sleep(1)


def frame():
    'Current counts, by object_id'
    snaplock.acquire()
    item_ids = set(errors.keys())
    item_ids.update(running_requests.keys())
    out = []
    for mid in item_ids:
        result = dict(item_id=mid,
                      errors=errors.get(mid, [0, ]),
                      requests=requests.get(mid, [0, ]))
        out.append(result)
    snaplock.release()
    return out


def space(seq, stop, prefix=None):
    if prefix:
        prefix = prefix(seq)
    else:
        prefix = ' '
    prefix = '%-4s' % prefix
    return prefix + ''.join(reversed(tuple('%-4s' % (x or '.')
                                           for x in islice(seq, stop)))).rjust(stop * 4)


def text_frame(nreqs=10, nerrors=10):
    out = ('#\treq ' + ''.join('%-4s' % x for x in range(nreqs - 1, -1, -1))
           + '\te/m e/s ' + ''.join('%-4s' % x for x in range(nerrors - 2, -1, -1)))
    for row in sorted(frame(), key=itemgetter('object_id')):
        textrow = str(row['object_id'])
        textrow += '\t' + space(row['requests'], nreqs,
                                lambda x: (sum(x) / len(x)))
        textrow += '\t' + space(row['errors'], nerrors, sum)
        out += '\n' + textrow
    return out, 'text/plain'


def json_frame(prefix):
    out = {}
    for row in frame():
        out[row['object_id']] = dict(requests=row['requests'][0],
                                       errors=row['errors'][0])
    return '%s(%s)' % (prefix, json.dumps(out)), 'application/javascript'


def start(target):
    t = threading.Thread(target=target)
    t.daemon = True
    t.start()


print 'Starting counter threads'
start(counter)
start(snappy)


def app(environ, start_response):
    """Simplest possible application object"""
    q = parse_qs(environ['QUERY_STRING'])
    if environ['PATH_INFO'] == "/jsonp":
        data, ct = json_frame(q['callback'][0])
    else:
        data, ct = text_frame(**dict((k, int(v[0])) for k, v in q.items()))
    status = '200 OK'
    response_headers = [
        ('Content-type', ct),
        ('Content-Length', str(len(data)))
    ]
    start_response(status, response_headers)
    return iter([data])
