# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
Exceptions.
"""

class WebSocketError(Exception):
    """
    Base class for all exceptions.
    """
    pass

class ConnectionClosingException(WebSocketError):
    """
    Raised if trying to write a message after close() was called.
    """
    pass

class ProtocolError(WebSocketError):
    """
    Exception for failure of the other side to adher to the protocol.

    The "code" attribute contains the error code, or None.
    """
    def __init__(self, message, code=None):
        """
        __init__(message, code=None) -> None

        Initialize a ProtocolError instance. message is passed
        to the superclass constructor, code is stored in the
        same-named attribute.
        """
        WebSocketError.__init__(self, message)
        self.code = code

class InvalidDataError(ProtocolError, ValueError):
    """
    Invalid data; raised by wsfile.WebSocketFile.parse_close().
    """
    pass
