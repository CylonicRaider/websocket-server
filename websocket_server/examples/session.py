# websocket_server -- WebSocket/HTTP server/client library
# https://github.com/CylonicRaider/websocket-server

"""
Example of an asynchronous client employing websocket_server.session.

To run:
- Start the chat server from the "server" example;
- Invoke "python3 -m websocket_server.examples.session WS-URL", where WS-URL
  is "ws://localhost:8080/chat" (if the server example is using the default
  settings);
- Visit <http://localhost:8080/?mode=chat> in your WebSocket-enabled browser,
  type "!echo something" into the input box, and press Return (NYI).
"""

import argparse

from .. import session

def run_bot(url):
    """
    Connect to the given WebSocket URL and respond to certain messages
    received from the connection.
    """
    sess = session.WebSocketSession.create(url)
    sess.connect(wait=False)
    try:
        sess.scheduler.join()
    except KeyboardInterrupt:
        sess.close()
        sess.scheduler.join()

def main():
    """
    Run the example. See run_bot() for the actual implementation.
    """
    p = argparse.ArgumentParser()
    p.add_argument('url', help='The WebSocket URL to connect to')
    arguments = p.parse_args()
    run_bot(arguments.url)

if __name__ == '__main__': main()
