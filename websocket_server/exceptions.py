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

class ProtocolError(WebSocketError):
    """
    Exception for failure of the other side to adher to the protocol.
    """
    pass

class InvalidDataError(WebSocketError, ValueError):
    """
    Invalid data; raised by wsfile.WebSocketFile.parse_close().
    """
    pass
