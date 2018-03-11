# websocket_server -- WebSocket/HTTP server/client library
# https://github.com/CylonicRaider/websocket-server

"""
Various tools and utilities.
"""

import os
import re
import calendar
import collections
import email.utils

from .compat import bytearray, xrange

try: # Py2K
    from urlparse import parse_qsl
except ImportError: # Py3K
    from urllib.parse import parse_qsl

__all__ = ['mask', 'new_mask', 'parse_paramlist', 'format_http_date',
           'parse_http_date', 'CaseDict', 'FormData']

def mask(key, data):
    """
    mask(key, data) -> bytearray

    Given a four-byte mask and an arbitrary-length data bytearray, mask /
    unmask the latter.
    May be in-place. Actually is in the current implementation. The result
    is returned in any case.
    """
    for i in xrange(len(data)):
        data[i] ^= key[i % 4]
    return data

def new_mask():
    """
    new_mask() -> bytearray

    Create a new mask value as conformant to the protocol.
    """
    return bytearray(os.urandom(4))

# RFC 2616, Section 2.2: A token is a sequence of characters that
# are not separators or control characters.
# The given RE is more permissive.
TOKEN_RE = re.compile(r'[^\0-\040\177()<>@,;:\\"/[\]?={}]+')
# Same source: A quoted string is a sequence of non-quote characters
# or quoted pairs enclosed by quotes.
QSTRING_RE = re.compile(r'"([^"]|\\.)*"')
# Any non-empty sequence of "linear whitespace".
LWS_RE = re.compile(r'\s+')

# Complete parameter regex.
PARAM_RE = re.compile(r'\s*(%s)\s*(=\s*(%s|%s)\s*)?' % (TOKEN_RE.pattern,
    TOKEN_RE.pattern, QSTRING_RE.pattern))

def parse_paramlist(string, allow_attributes=True):
    """
    parse_paramlist(string, allow_attributes=True) -> list

    Parse a comma-delimited sequence of tokens with HTTP-style attributes
    (like, "foo; bar=baz"); the return value is a list of the form
    [['foo', 'bar=baz']], to re-use the given example. If allow_attributes
    is false, attributes as described above are not allowed, and the
    return value is a non-nested list of strings instead.
    May raise ValueError if the string does not conform.
    I could seriously not find anything in the standard library that would
    do that.
    """
    # Variables.
    ret, offset, in_params = [], 0, False
    # Main loop.
    while offset < len(string):
        # Discard whitespace.
        m = LWS_RE.match(string, offset)
        if m:
            offset = m.end()
            continue
        # If inside parameters...
        if in_params:
            # Validate separator.
            if string[offset] == ',':
                # Reached end, another parameter following.
                offset += 1
                in_params = False
                continue
            elif string[offset] != ';':
                raise ValueError('Invalid parameter list: %r' % (string,))
            # Enforce allow_attributes
            if not allow_attributes:
                raise ValueError('Attributes not allowed (%r)' % (string,))
            # ...Append another parameter.
            m = PARAM_RE.match(string, offset + 1)
            if not m:
                raise ValueError('Invalid parameter list: %r' % (string,))
            if m.group(2):
                ret[-1].append(m.group(1) + '=' + m.group(3))
            else:
                ret[-1].append(m.group(1))
            offset = m.end()
        else:
            # Match another "top-level" value.
            m = TOKEN_RE.match(string, offset)
            if not m:
                raise ValueError('Invalid parameter list: %r' % (string,))
            # Create new entry.
            ret.append([m.group()])
            offset = m.end()
            # Possible parameters following
            in_params = True
    # Post-process list.
    if allow_attributes:
        return ret
    else:
        return [i[0] for i in ret]

def format_http_date(t):
    """
    format_http_date(t) -> str

    Return a string represententing the given UNIX timestamp suitable for
    inclusion into HTTP headers.
    """
    return email.utils.formatdate(t, usegmt=True)

def parse_http_date(s):
    """
    parse_http_date(s) -> int

    Parse a timestamp as it occurs in HTTP and return the corresponding UNIX
    time.
    """
    return calendar.timegm(email.utils.parsedate(s))

class CaseDict(collections.MutableMapping):
    """
    CaseDict(source=(), **update) -> new instance

    A mapping with case-insensitive (string) keys (the class name is
    abbreviated from CaseInsensitiveDict). See the dict constructor for
    the meanings of the arguments.
    """

    def __init__(_self, _source=(), **_update):
        """
        __init__(source=(), **update) -> None

        See class docstring for details.
        """
        super(CaseDict, _self).__init__()
        _self._data = dict(_source, **_update)
        _self._keys = dict((k.lower(), k) for k in _self._data)

    def __repr__(self):
        """
        repr(self) -> str

        Return a programmer-friendly string representation of self.
        """
        return '%s(%r)' % (self.__class__.__name__, self._data)

    def __iter__(self):
        """
        iter(self) -> iter

        Return an iterator over self.
        """
        return iter(self._data)

    def __len__(self):
        """
        len(self) -> int

        Return the length of self.
        """
        return len(self._data)

    def __contains__(self, key):
        """
        key in self -> bool

        Check whether the given key is contained in self.
        """
        return (key.lower() in self._keys)

    def __getitem__(self, key):
        """
        self[key] -> value

        Return the value associated with the given key.
        """
        return self._data[self._keys[key.lower()]]

    def __setitem__(self, key, value):
        """
        self[key] = value

        Assign the given value to the given key.
        """
        self._data[self._keys.setdefault(key.lower(), key)] = value

    def __delitem__(self, key):
        """
        del self[key]

        Remove the given key from self.
        """
        lower_key = key.lower()
        del self._data[self._keys[lower_key]]
        del self._keys[lower_key]

class FormData:
    """
    FormData(pairs=()) -> new instance

    A read-only mapping-like representation of a set of key-value pairs with
    potentially non-unique keys. Intended for convenient retrieval of data
    from HTML form data or query strings.

    pairs is an iterable of (key, value) pairs. The relative order of values
    (per key) is preserved, as is the order of keys (by first appearance).

    The subscript operator (x[y]) and the get() method are geared towards the
    simultaneous retrieval of multiple keys, and return a single value if
    applied to a single key, or a list of values when applied to multiple
    keys. See their docstrings (and get_ex()) for more details.
    """

    @classmethod
    def from_qs(cls, qs, **kwds):
        """
        from_qs(qs, **kwds) -> new instance

        Parse a query string and convert the result into a FormData instance.
        Keyword arguments are forwarded to the parse_qsl() function.
        """
        return cls(parse_qsl(qs, **kwds))

    @classmethod
    def from_dict(cls, src):
        """
        from_dict(src) -> new instance

        Convert a mapping where each key is mapped to an iterable of values
        to a corresponding FormData instance.
        """
        def make_pairs():
            for k, v in src.items():
                for e in v:
                    yield (k, e)
        return cls(make_pairs())

    def __init__(self, pairs=()):
        """
        __init__(pairs=()) -> None

        Instance initializer; see the class docstring for details.
        """
        self.data = collections.OrderedDict()
        for k, v in pairs:
            self.data.setdefault(k, []).append(v)

    def __bool__(self):
        """
        bool(self) -> bool

        Return whether this instance is nonempty.
        """
        return bool(self.data)

    def __nonzero__(self):
        """
        bool(self) -> bool

        Return whether this instance is nonempty.
        """
        return bool(self.data)

    def __getitem__(self, key):
        """
        self[key] -> value

        This is equivalent to self.get_ex(key), or self.get_ex(*key) if
        key is a tuple or a list.
        """
        if isinstance(key, (tuple, list)):
            return self.get_ex(*key)
        else:
            return self.get_ex(key)

    def keys(self):
        """
        keys() -> keys

        Return the keys of this mapping. Note that attempting to subscript
        this instance with each key may still fail (if there are multiple
        values for it); use get_all() to retrieve all values corresponding
        to a key reliably.
        """
        return self.data.keys()

    def get_all(self, key, **kwds):
        """
        get_all(key, [default]) -> list

        Return all values corresponding to key, or default if given, or raise
        a KeyError.
        """
        try:
            return self.data[key]
        except KeyError:
            try:
                return kwds['default']
            except KeyError:
                raise KeyError(key)

    def get_ex(self, *keys, **kwds):
        """
        get_ex(*keys, [default], first=False, list=False) -> list or str

        Retrieve values corresponding to keys. If default is not omitted,
        it is substituted for keys for which there is *no* value. If first is
        false and there are multiple values for a key, a KeyError is raised;
        otherwise, the first (or only) value for the key is returned. If
        list is false and there is only one key, only the value corresponding
        to it is retrieved; otherwise, a (potentially one-element) list of
        values is returned.
        """
        first, always_list, ret = kwds.get('first'), kwds.get('list'), []
        for k in keys:
            v = self.data.get(k, ())
            if not v:
                try:
                    ret.append(kwds['default'])
                except KeyError:
                    raise KeyError('No value for %r' % (k,))
            elif len(v) > 1 and not first:
                raise KeyError('Too many values for %r' % (k,))
            else:
                ret.append(v[0])
        if len(ret) == 1 and not always_list: ret = ret[0]
        return ret

    def get(self, *keys, **kwds):
        """
        get(*keys, default=None, first=False, list=False) -> list or str

        Retrieve values corresponding to keys, substituting default where
        there is no value corresponding to a key. Note that here, default is
        always defined (and itself defaults to None).
        """
        kwds.setdefault('default', None)
        return self.get_ex(*keys, **kwds)

    def items(self):
        """
        items() -> iterator

        Iterate over all items in self in approximate insertion order.
        """
        for k, v in self.data.items():
            for e in v:
                yield (k, e)
