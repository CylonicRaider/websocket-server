# websocket_server -- WebSocket/HTTP server/client library
# https://github.com/CylonicRaider/websocket-server

"""
WebSocket server library

This is a small stand-alone library for WebSocket servers/clients and generic
HTTP servers. It extends Python's HTTP server framework, providing -- aside
from WebSocket functionality -- convenient use of cookies, query string
parameters, POSTed HTML forms, request routing, and richer HTTP logs than
the standard library provides. WebSocket client functionality is provided as
well.

For an example usage, see the examples subpackage; for reference
documentation, see the wsfile, cookies, httpserver, server, and client
modules; also see the quick module for further convenience functions.
"""

__version__ = '2.0'

# Auxiliary modules
from . import compat, constants, exceptions, tools
# Main modules
from . import wsfile, cookies, httpserver, server, client, session
# Helper modules
from . import quick

__all__ = constants.__all__ + exceptions.__all__
__all__ += ['WebSocketFile', 'wrap', 'connect', 'create_connection',
            'WebSocketRequestHandler']

from .constants import *
from .exceptions import *
from .wsfile import WebSocketFile, wrap
from .client import connect, create_connection
from .server import WebSocketRequestHandler
