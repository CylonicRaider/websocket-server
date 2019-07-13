# websocket_server -- WebSocket/HTTP server/client library
# https://github.com/CylonicRaider/websocket-server

"""
Example usage of the package.

To run:
- python3 -m websocket_server.examples.server
- Open http://localhost:8080/ in your WebSocket-enabled Web browser.
"""

import pkgutil

from ..exceptions import ProtocolError
from ..httpserver import RouteSet, HTTPError # FileCache not used for now
from ..quick import RoutingWebSocketRequestHandler, run

route = RouteSet()

@route('/echo')
def handle_echo(self):
    "Accept a WebSocket connection and bounce received messages back."
    try:
        conn = self.handshake()
    except ProtocolError:
        raise HTTPError(400)
    # Read frames, and write them back.
    while 1:
        try:
            msg = conn.read_frame()
            if not msg: break
            conn.write_frame(msg[0], msg[1])
        except ProtocolError as exc:
            self.log_error('%r', exc)
            break

@route('/')
def route_root(self):
    "Serve a static page at the root."
    page = pkgutil.get_data(__package__, 'testpage.html')
    self.send_text(200, page, 'text/html; charset=utf-8')

def main():
    """
    Run the example. Uses the run() function from the quick module.
    """
    run(route.build(RoutingWebSocketRequestHandler))

if __name__ == '__main__': main()
