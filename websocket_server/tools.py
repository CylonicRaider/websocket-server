# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
Various tools and utilities.
"""

import os
import re

from .compat import bytes, xrange

__all__ = ['mask', 'new_mask', 'parse_paramlist']

def mask(mask, data):
    """
    mask(mask, data) -> bytearray

    Given a four-byte mask and an arbitrary-length data bytearray, mask /
    unmask the latter.
    May be in-place. Actually is in the current implementation. The result
    is returned in any case.
    """
    for i in xrange(len(data)):
        data[i] ^= mask[i % 4]
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
LWS_RE = re.compile('\s+')

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
