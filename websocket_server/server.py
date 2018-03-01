# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
Server implementation.

Relies on the standard library's HTTPServer as the actual server.
"""

from .compat import BaseHTTPRequestHandler
from .exceptions import ProtocolError
from .wsfile import server_handshake, wrap

__all__ = ['WebSocketRequestHandler']

class WebSocketRequestHandler(BaseHTTPRequestHandler):
    """
    Extension of BaseHTTPRequestHandler allowing to handle WebSockets.

    Use the handshake() method in do_*() method to actually initiate a
    WebSocket connections; the handler method must not return until the
    session ends.
    This class does not include any mix-ins, however, you are strongly
    advised to use ThreadingMixIn (or ForkingMixIn), as otherwise the
    server will only accept one WebSocket session at a time.
    """

    # Override default from StreamRequestHandler
    rbufsize = 0

    def handshake(self):
        """
        handshake() -> WebSocketFile

        Perform a WebSocket handshake and return a WebSocketFile
        representing the current session.
        Raises ProtocolError if the request is not a valid WebSocket
        handshake.
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
        Raises ProtocolError if the request is not a valid WebSocket
        handshake.
        """
        try:
            respheaders = server_handshake(self.headers,
                                           self.process_subprotocols)
        except ProtocolError as e:
            self._error(e.args[0])
            raise
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

    def error(self, code=400, message=None):
        """
        error(code=400, message=None) -> None

        Convenience method for indicating an error.
        The default implementation returns code as the HTTP status code to
        the client, and adds message (if non-None) as a text/plain UTF-8
        encoded request body.
        """
        self.send_response(code)
        if message is not None:
            enc = message.encode('utf-8')
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', len(enc))
            self.end_headers()
            self.wfile.write(enc)
            self.wfile.flush()
        else:
            self.send_header('Content-Length', 0)
            self.end_headers()
