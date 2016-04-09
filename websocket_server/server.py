# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
Server implementation.

Relies on the standard library's HTTPServer as the actual server.
"""

import base64
import hashlib

from .compat import unicode, tobytes, BaseHTTPRequestHandler
from .exceptions import ProtocolError
from .wsfile import wrap
from .tools import parse_paramlist

__all__ = ['WebSocketRequestHandler']

# The "magic" GUID used for Sec-WebSocket-Accept.
MAGIC_GUID = unicode('258EAFA5-E914-47DA-95CA-C5AB0DC85B11')

def process_key(key):
    """
    process_key(key) -> unicode

    Transform the given key as required to form a Sec-WebSocket-Accept
    field, and return the new key.
    """
    enc_key = (unicode(key) + MAGIC_GUID).encode('ascii')
    key_reply = base64.b64encode(hashlib.sha1(enc_key).digest())
    return key_reply.decode('ascii')

class WebSocketRequestHandler(BaseHTTPRequestHandler):
    """
    Extension of BaseHTTPRequestHandler allowing to handle WebSockets.

    Use the handshake() method in do_*() method to actually initiate a
    WebSocket connections; the handler method must not return until the
    session ends.
    This class does not include and mix-ins, however, you are strongly
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
        self.perform_handshake()
        # Wrap the stream in a WebSocket.
        return self.wrap()

    def perform_handshake(self):
        """
        perform_handshake() -> None

        Effectively perform the WebSocket handshake.
        Raises ProtocolError if the request is not a valid WebSocket
        handshake.
        """
        # Validate the handshake.
        # General HTTP-level validation is done be the parent class.
        # Validate the various headers.
        if 'Host' not in self.headers:
            self._error(message='Missing Host header')
        if 'websocket' not in self.headers.get('Upgrade', '').lower():
            self._error(message='Invalid/Missing Upgrade header')
        # Validate protocol version (why does the standard list that
        # as the last mandatory one?)
        if self.headers.get('Sec-WebSocket-Version') != '13':
            self._error(message='Invalid WebSocket version (!= 13)')
        # (In particular, the Connection header.)
        connection = [i.lower().strip()
            for i in self.headers.get('Connection', '').split(',')]
        if 'upgrade' not in connection:
            self._error(message='Invalid/Missing Connection header')
        # Validate the key.
        key = self.headers.get('Sec-WebSocket-Key')
        try:
            if len(base64.b64decode(tobytes(key))) != 16:
                self._error(message='Invalid WebSocket key length')
        except (TypeError, ValueError):
            self._error(message='Invalid WebSocket key')
        # Process extensions and subprotocols.
        try:
            extstr = self.headers.get('Sec-WebSocket-Extensions', '')
            exts = parse_paramlist(extstr)
        except ValueError:
            self._error(message='Invalid extension string')
        self.process_extensions(exts)
        # Be permissive with subprotocol tokens.
        protstr = self.headers.get('Sec-WebSocket-Protocol', '')
        protstr = protstr.split()
        if protstr:
            protocols = [i.strip() for i in protstr.split(',')]
        else:
            protocols = []
        self.process_subprotocols(protocols)
        # Allow any post-processing.
        self.postprocess_handshake()
        # Send a handshake reply.
        self.send_response(101)
        self.handshake_reply(key, exts, protocols)
        self.end_headers()
        self.wfile.flush()

    def process_extensions(self, exts):
        """
        process_extensions(exts) -> None

        Process the given extension requests.
        exts is a parameter list as returned by tools.parse_paramlist().
        The default implementation discards all the extension requests.
        May call error() to reject a request.
        Extending classes must send the reply header themself.
        """
        pass

    def process_subprotocols(self, prots):
        """
        process_extensions(prots) -> None

        Process the given subprotocol requests.
        prots is a list of strings.
        The default implementation rejects the request if a non-supported
        subprotocol (i.e., any subprotocol at all) is present.
        May call error() to reject a request.
        Extending classes must send the reply header themself.
        """
        if prots: self._error(message='Unsupported subprotocols present')

    def postprocess_handshake(self):
        """
        postprocess_handshake() -> None

        Performs any post-processing of a handshake after it has been
        validated.
        The default implementation does nothing.
        """
        pass

    def handshake_reply(self, key, exts, prots):
        """
        handshake_reply(key, exts, prots) -> None

        Construct and send a handshake reply.
        key is the unmodified WebSocket key; exts and prots are the
        extensions and subprotocols, as elaborated in process_extensions()
        and in process_subprotocols().
        The default implementation sends a confirming Sec-WebSocket-Allow
        header back, and should hence be called by extending classes,
        unless they implement that on their own.
        end_headers() must not be called; that happens in
        perform_handshake().
        """
        key_reply = process_key(key)
        self.send_header('Upgrade', 'websocket')
        self.send_header('Connection', 'Upgrade')
        self.send_header('Sec-WebSocket-Accept', key_reply)

    def wrap(self):
        """
        wrap() -> WebSocketFile

        Wrap this handler's connection into a server-side WebSocketFile.
        The default implementation calls wsfile.wrap().
        """
        ws = wrap(self.rfile, self.wfile, server_side=True)
        # Is done in self.finish().
        ws.close_wrapped = False
        ws._socket = self.connection
        return ws

    # Used internally.
    def _error(self, code=400, message=None):
        self.error(code, message)
        raise RuntimeError('error() did return')

    def error(self, code=400, message=None):
        """
        error(code=400, message=None) -> None

        Convenience method for indicating an error.
        The default implementation returns code as the HTTP status code to
        the client, and adds message (if non-None) as a text/plain UTF-8
        encoded request body, and raises a ProtocolError with no error
        code.
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
        raise ProtocolError('Invalid handshake')
