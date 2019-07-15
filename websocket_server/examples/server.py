# websocket_server -- WebSocket/HTTP server/client library
# https://github.com/CylonicRaider/websocket-server

"""
Example usage of the WebSocket (and HTTP) server functionality.

To run:
- python3 -m websocket_server.examples.server
- Open http://localhost:8080/ in your WebSocket-enabled Web browser.
"""

import threading
import pkgutil

from ..exceptions import ProtocolError
from ..httpserver import RouteSet, HTTPError # FileCache not used for now
from ..quick import RoutingWebSocketRequestHandler, run

class MessageRelay(object):
    """
    An elementary broadcasting message distributor.

    Processes (e.g. connection handler threads) wishing to receive messages
    subscribe/unsubscribe using the listen()/unlisten() methods, respectively;
    processes wishing to send messages do so via the broadcast() method.

    The constructor takes no arguments.
    """

    def __init__(self):
        "Instance initializer; see the class docstring for details."
        self.clients = set()
        self.lock = threading.RLock()

    def listen(self, callback):
        """
        Register the given callback for receiving messages.

        When a message is broadcast(), the callback is invoked upon the
        message object.
        """
        with self.lock:
            self.clients.add(callback)

    def unlisten(self, callback):
        """
        Cancel the given callback's registration for receiving messages.

        callback must be an object that had been passed to listen()
        previously; if it is not, it is ignored.
        """
        with self.lock:
            self.clients.discard(callback)

    def broadcast(self, message):
        """
        Distribute the given message to all registered callbacks.
        """
        with self.lock:
            for c in self.clients:
                try:
                    c(message)
                except Exception:
                    self.clients.discard(c)

route = RouteSet()

@route('/echo')
def handle_echo(self):
    "Accept a WebSocket connection and bounce received messages back."
    try:
        conn = self.handshake()
    except ProtocolError:
        raise HTTPError(400)
    # Read frames, and write them back.
    try:
        while 1:
            msg = conn.read_frame()
            if not msg: break
            conn.write_frame(msg.msgtype, msg.content)
    except ProtocolError as exc:
        self.log_error('%r', exc)
    finally:
        conn.close()

@route('/chat')
def handle_chat(self):
    "Accept a WebSocket connection and broadcast received messages."
    def callback(message):
        "Callback for the message relay."
        conn.write_frame(message[0], message[1])
    try:
        conn = self.handshake()
    except ProtocolError:
        raise HTTPError(400)
    # Read frames, broadcast them into the relay.
    try:
        self.relay.listen(callback)
        while 1:
            msg = conn.read_frame()
            if not msg: break
            self.relay.broadcast(msg)
    except ProtocolError as exc:
        self.log_error('%r', exc)
    finally:
        self.relay.unlisten(callback)
        conn.close()

@route('/')
def route_root(self):
    "Serve a static page at the root."
    page = pkgutil.get_data(__package__, 'testpage.html')
    self.send_text(200, page, 'text/html; charset=utf-8')

def main():
    """
    Run the example. Uses the run() function from the quick module.
    """
    run(route.build(RoutingWebSocketRequestHandler,
                    {'relay': MessageRelay()}))

if __name__ == '__main__': main()
