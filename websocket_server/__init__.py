# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
WebSocket server library

This is a little stand-alone library for WebSocket servers.
It integrates neatly with the standard library, providing easily set-up
servers for both WebSockets and other content. It is intended for small-
scale usages, where installing a proper framework would require too much
work.

TLS support is out of scope of this package; for setting up a TLS-enabled
WebSocket server, refer to online sources on how to achieve that using
HTTPServer.

For an example usage, see the examples module, for reference
documentation, see the wsfile and server modules; also see the quick
module for further convenience functions.
"""

__version__ = '1.0'

# Auxiliary modules
from . import compat, constants, exceptions, tools
# Main modules
from . import cookies, wsfile, server, client, quick, examples

__all__ = constants.__all__ + exceptions.__all__
__all__ += ['WebSocketFile', 'wrap', 'WebSocketRequestHandler']

from .constants import *
from .exceptions import *
from .wsfile import WebSocketFile, wrap
from .server import WebSocketRequestHandler
