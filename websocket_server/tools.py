# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
Various tools and utilities.
"""

import os

from .compat import bytes, xrange

__all__ = ['mask', 'new_mask']

def mask(mask, data):
    """
    mask(mask, data) -> bytearray

    Given a four-byte mask and an arbitrary-length data bytearray,
    mask/unmask the latter.
    May be in-place. The result is returned in any case.
    """
    for i in xrange(len(data)):
        data[i] ^= mask[i % 4]
    return data

def new_mask():
    """
    new_mask() -> bytearray

    Create a new mask value as conformant to the protocol.
    """
    return bytes(os.urandom(4))
