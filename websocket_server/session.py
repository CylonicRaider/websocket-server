# websocket_server -- WebSocket/HTTP server/client library
# https://github.com/CylonicRaider/websocket-server

"""
Support for "sessions" spanning multiple WebSocket connections.

In some (or many) cases, multiple WebSocket connections to the same URL are
(mostly) interchangeable. This module caters for that case by providing a
WebSocketSession class that transparently handles re-connecting to a WebSocket
endpoint, retrying commands whose results may have been missed, etc.

This module is NYI.
"""

import threading

__all__ = ['WebSocketSession']

class WebSocketSession(object):
    """
    WebSocketSession(url) -> new instance

    A "session" spanning multiple WebSocket connections. url is the WebSocket
    URL to connect to.

    The constructor parameter is stored in a same-named instance variable; it
    may be modified to change where future connections are going to go.
    """

    def __init__(self, url):
        """
        __init__(url) -> None

        Instance initializer; see the class docstring for details.
        """
        self.url = url
        self.cond = threading.Condition()
        self._conn = None

    def __enter__(self):
        "Context manager entry; internal."
        self.cond.__enter__()

    def __exit__(self, *args):
        "Context manager exit; internal."
        self.cond.__exit__(*args)
