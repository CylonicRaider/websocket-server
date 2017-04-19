# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
Various tools and utilities.
"""

import os
import re
import time
import calendar
import collections

from .compat import bytearray, xrange

__all__ = ['mask', 'new_mask', 'parse_paramlist']

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

# Preferred datetime format from RFC 2616.
DATETIME_RE = re.compile((r'^(?P<a>\w+), (?P<d>\d+) (?P<b>\w+) (?P<Y>\d+) '
    r'(?P<H>\d+):(?P<M>\d+):(?P<S>\d+) GMT$').replace(' ', r'\s+'))
# Month names.
MONTHS = { 1: 'Jan',  2: 'Feb',  3: 'Mar',  4: 'Apr',
           5: 'May',  6: 'Jun',  7: 'Jul',  8: 'Aug',
           9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec'}
REVMONTHS = dict((v.lower(), k) for k, v in MONTHS.items())
# Names of days of the week.
WDAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')

# ISO 8601 datetiem format.
ISO_DATETIME_RE = re.compile(r'(?P<Y>\d+) - (?P<m>\d+) - (?P<d>\d+) T? '
    r'(?P<H>\d+) : (?P<M>\d+) : (?P<S>\d+) Z?'.replace(' ', r'\s*'))

def parse_http_date(s):
    """
    parse_http_date(s) -> int

    Parse a timestamp as it occurs in HTTP and return the corresponding UNIX
    time.
    """
    # Since strptime() depends on the locale, we'll do the parsing ourself.
    m = DATETIME_RE.match(s.strip())
    if m:
        # Interpret month name.
        try:
            month = REVMONTHS[m.group('b').lower()]
        except KeyError:
            raise ValueError('Bad date')
        # Assemble time struct.
        struct = (int(m.group('Y')), month, int(m.group('d')),
                  int(m.group('H')), int(m.group('M')), int(m.group('S')),
                  0, 0, 0)
    else:
        # ISO 8601, perhaps?
        m = ISO_DATETIME_RE.match(s.strip())
        if not m: raise ValueError('Bad date')
        struct = (int(m.group('Y')), int(m.group('m')), int(m.group('d')),
                  int(m.group('H')), int(m.group('M')), int(m.group('S')),
                  0, 0, 0)
    # Return corresponding timestamp.
    return calendar.timegm(struct)

def format_http_date(t):
    """
    format_http_date(t) -> str

    Return a string represententing the given UNIX timestamp suitable for
    inclusion into HTTP headers.
    """
    struct = time.gmtime(t)
    ret = time.strftime('#a, %d #b %Y %H:%M:%S GMT', struct)
    return ret.replace('#a', WDAYS[struct[6]]).replace('#b',
                                                       MONTHS[struct[1]])

class CaseDict(collections.MutableMapping):
    """
    CaseDict(source=(), **update) -> new instance

    A mapping with case-insensitive (string) keys (the name is
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
