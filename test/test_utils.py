from nose.tools import eq_, ok_
from contexture import utils

d = dict(a=1, b=2, x=dict(a=3, c=4))


def test_remove_keys():
    # Remove all a's
    eq_(utils.remove_keys(d, 'a'), {'b': 2, 'x': {'c': 4}})
    # Remove all a's and b's
    eq_(utils.remove_keys(d, ('a', 'b')), {'x': {'c': 4}})


def test_extract_keys():
    # Get the first "a"
    eq_(utils.extract_keys(d, ['a']), {'a': 1})
    # Get a nested thing
    eq_(utils.extract_keys(d, ['c']), {'c': 4})
    # Get all "a"s
    eq_(utils.extract_keys(d, ['*a']), {'a': (1, 3)})


def test_filter_dict_empty():
    filtered = utils.filter_dict_empty(dict(x=[]))
    eq_(filtered, {})
