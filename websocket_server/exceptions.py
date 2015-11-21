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

    May have an additional "code" attribute, containing the error code.
    """
    code = None

class InvalidDataError(WebSocketError, ValueError):
    """
    Invalid data; raised by wsfile.WebSocketFile.parse_close().
    """
    pass
