# websocket_server -- WebSocket/HTTP server/client library
# https://github.com/CylonicRaider/websocket-server

"""
Exceptions.
"""

__all__ = ['WebSocketError', 'ProtocolError', 'InvalidDataError',
           'ConnectionClosedError']

class WebSocketError(Exception):
    """
    Base class for all exceptions.
    """

class ProtocolError(WebSocketError):
    """
    Exception for failure of the other side to adher to the protocol.

    The "code" attribute contains the error code (a CLOSE_* from the
    constants module) or None.
    """

    def __init__(self, message, code=None):
        """
        __init__(message, code=None) -> None

        Initialize a ProtocolError instance. message is passed to the
        superclass constructor, code is stored in the same-named
        attribute.
        """
        WebSocketError.__init__(self, message)
        self.code = code

class InvalidDataError(ProtocolError, ValueError):
    """
    Invalid data have been encountered.
    """

class ConnectionClosedError(WebSocketError):
    """
    Raised when trying to write a message after the connection closed.
    """
