from collections import OrderedDict
from itertools import chain, islice


class adict(dict):
    def __init__(self, *args, **kwargs):
        super(adict, self).__init__(*args, **kwargs)
        self.__dict__ = self


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
    result = OrderedDict()
    for key in keys:
        if key.startswith('*'):
            key = key.lstrip('*')
            result[key] = tuple(findkey(d, key))
        else:
            result[key] = tuple(islice(findkey(d, key), 1))
        if len(result[key]) == 1:
            result[key] = result[key][0]
    return result


def remove_keys(d, keys):
    if not isinstance(keys, set):
        keys = set(keys)
    if isinstance(d, dict):
        d = {k: remove_keys(v, keys) for k, v in d.iteritems() if k not in keys}
    return d


def filter_dict(d, filter_func):
    if isinstance(d, dict):
        d = {k: filter_dict(v, filter_func) for k, v in d.iteritems() if filter_func(k, v)}
    return d


def filter_dict_empty(d):
    return filter_dict(d, lambda k, v: bool(v))
