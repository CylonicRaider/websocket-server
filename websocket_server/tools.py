# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
Various tools and utilities.
"""

import os
import re
import time
import calendar

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

def parse_rfc2616_date(s):
    """
    parse_rfc2616_date(s) -> int

    Parse a timestamp as it occurs in HTTP and return the corresponding UNIX
    time.
    """
    # Since strptime() depends on the locale, we'll do the parsing ourself.
    m = DATETIME_RE.match(s.strip())
    if not m: raise ValueError('Bad date')
    # Interpret month name.
    try:
        month = REVMONTHS[m.group('m').lower()]
    except KeyError:
        raise ValueError('Bad date')
    # Assemble time struct.
    struct = (int(m.group('Y')), month, int(m.group('d')),
              int(m.group('H')), int(m.group('M')), int(m.group('S')),
              0, 0, 0)
    # Return corresponding timestamp.
    return calendar.timegm(struct)

def format_rfc2616_date(t):
    """
    format_rfc2616_date(t) -> str

    Return a string represententing the given UNIX timestamp suitable for
    inclusion into HTTP headers.
    """
    struct = time.gmtime(t)
    ret = time.strftime('#a, %d #b %Y %H:%M:%S GMT', struct)
    return ret.replace('#a', WDAYS[struct[6]]).replace('#b',
                                                       MONTHS[struct[1]])
