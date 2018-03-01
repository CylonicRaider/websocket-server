# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
Py2K/Py3K compatibility utilities.
"""

try: # Py2K
    unicode = unicode
except NameError: # Py3K
    unicode = str

try: # Py3K; backported to 2.6
    bytes = bytes
except NameError: # Py2K
    bytes = str

# Works in both Py2K and Py3K.
bytearray = bytearray

try: # Py2K
    xrange = xrange
except NameError:
    # Py3K
    xrange = range

try: # Py2K and recent Py3K
    callable = callable
except NameError:
    # Python 3.0 and 3.1.
    callable = lambda x: hasattr(x, '__call__')

import sys as _sys
if _sys.version_info[0] <= 2:
    def tobytes(s):
        return s
else:
    def tobytes(s):
        return bytes(s, 'utf-8')
del _sys

try: # Py2K
    from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
    from SocketServer import ThreadingMixIn
except ImportError: # Py3K
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from socketserver import ThreadingMixIn
