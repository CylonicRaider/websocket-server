# websocket_server -- WebSocket/HTTP server/client library
# https://github.com/CylonicRaider/websocket-server

"""
WebSocket server implementation.

Relies on the standard library's HTTP server framework for the HTTP serving
part; is also compatible with the websocket_server.httpserver module.
"""

from .wsfile import server_handshake, wrap

try: # Py2K
    from BaseHTTPServer import BaseHTTPRequestHandler
except ImportError: # Py3K
    from http.server import BaseHTTPRequestHandler

__all__ = ['WebSocketMixIn', 'WebSocketRequestHandler']

class WebSocketMixIn:
    """
    Mixin class for BaseHTTPRequestHandler implementing WebSocket handshakes.

    Use the handshake() method in a do_*() method to actually initiate a
    WebSocket connection; do not return from the handler method until the
    WebSocket session ends.
    You are advised to use the ThreadingMixIn in your server class to allow
    handling multiple WebSocket connections concurrently.
    """

    def handshake(self):
        """
        handshake() -> WebSocketFile

        Perform a WebSocket handshake and return a WebSocketFile
        representing the current session.
        Raises a ProtocolError (without sending an HTTP response) if the
        request is not a valid WebSocket handshake.
        """
        # Perform actual handshake.
        proto = self.perform_handshake()
        # Wrap the stream in a WebSocket.
        return self.wrap(proto)

    def perform_handshake(self):
        """
        perform_handshake() -> str or None

        Effectively perform the WebSocket handshake.
        Returns the subprotocol to be used, or None for none.
        Raises a ProtocolError (without sending an HTTP response) if the
        request is not a valid WebSocket handshake.
        """
        respheaders = server_handshake(self.headers,
                                       self.process_subprotocols)
        # Send a handshake reply.
        self.send_response(101)
        for header, value in respheaders.items():
            self.send_header(header, value)
        self.end_headers()
        self.wfile.flush()
        return respheaders.get('Sec-WebSocket-Protocol')

    def process_subprotocols(self, protos):
        """
        process_subprotocols(protos) -> str or None

        Process the given subprotocol requests.
        protos is a list of strings denoting the subprotocols the client
        wishes to use in order of preference.
        The return value is either a string denoting the subprotocol to use
        (which must be in protos), or None for none.
        The default implementation returns None.
        """
        return None

    def wrap(self, proto=None):
        """
        wrap(proto=None) -> WebSocketFile

        Wrap this handler's connection into a server-side WebSocketFile.
        proto is the subprotocol to be used by the WebSocket; it is set as
        the corresponding member of the return value.
        The default implementation calls wsfile.wrap().
        """
        ws = wrap(self.rfile, self.wfile, server_side=True)
        ws.subprotocol = proto
        # Is done in self.finish().
        ws.close_wrapped = False
        ws._socket = self.connection
        return ws

class WebSocketRequestHandler(BaseHTTPRequestHandler, WebSocketMixIn):
    """
    An HTTP request handler with support for WebSocket handshakes.
    """
