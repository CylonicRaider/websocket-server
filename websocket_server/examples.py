# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
Example usage of the package.
"""

import sys
import optparse
import pkgutil

try:
    from BaseHTTPServer import HTTPServer
except ImportError:
    from http.server import HTTPServer
try:
    from SocketServer import ThreadingMixIn
except ImportError:
    from socketserver import ThreadingMixIn

from .exceptions import ProtocolError
from .server import WebSocketRequestHandler

# "Page" to display in case of a 404.
NOT_FOUND = b'404 Not Found'

class EchoRequestHandler(WebSocketRequestHandler):
    """
    Echo-back WebSocketRequestHandler.

    Reads a message, and writes it back, until the client
    closes the connection.
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

# Multi-threaded HTTP server.
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer): pass

def main():
    # Parse command-line arguments.
    p = optparse.OptionParser()
    p.add_option('-p', '--port', dest='port', type='int',
                 default=8080,
                 help='Specify the port to run on.',
                 metavar='PORT')
    options, arguments = p.parse_args()
    # Create server.
    httpd = ThreadingHTTPServer(('', options.port), EchoRequestHandler)
    # Print status message.
    sys.stderr.write('Serving HTTP on port %s...\n' % options.port)
    sys.stderr.flush()
    # Run it.
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        # Don't print a noisy stack trace if Ctrl+C'ed.
        pass

if __name__ == '__main__': main()
