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

try:
    # Py2K
    xrange = xrange
except NameError:
    # Py3K
    xrange = range
