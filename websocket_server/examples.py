# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
Example usage of the package.

To run:
- python3 -m websocket_server.examples
- Open http://localhost:8080/ in your WebSocket-enabled Web browser.
"""

import pkgutil

from .exceptions import ProtocolError
from .server import WebSocketRequestHandler
from .quick import run # FileCache not used for now

__all__ = ['EchoRequestHandler']

# "Page" to display in case of a 404.
NOT_FOUND = b'404 Not Found'

class EchoRequestHandler(WebSocketRequestHandler):
    """
    Echo-back WebSocketRequestHandler.

    Reads a message, and writes it back, until the client closes the
    connection.
    """
    def do_GET(self):
        """
        do_GET() -> None

        Example server main loop. See source code for details.
        """
        if self.path == '/echo':
            try:
                conn = self.handshake()
            except ProtocolError:
                return
            # Read frames, and write them back.
            while 1:
                try:
                    msg = conn.read_frame()
                    if not msg: break
                    conn.write_frame(msg[0], msg[1])
                except ProtocolError as exc:
                    self.log_error(repr(exc))
                    break
        elif self.path == '/':
            # Display HTML test page.
            page = pkgutil.get_data(__package__, 'testpage.html')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(page))
            self.end_headers()
            self.wfile.write(page)
        else:
            # Minimalistic 404 response.
            self.send_response(404)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', len(NOT_FOUND))
            self.end_headers()
            self.wfile.write(NOT_FOUND)

def main():
    """
    Run the example. Uses the run() function from the quick module.
    """
    run(EchoRequestHandler)

if __name__ == '__main__': main()
