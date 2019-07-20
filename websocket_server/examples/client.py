# websocket_server -- WebSocket/HTTP server/client library
# https://github.com/CylonicRaider/websocket-server

"""
Example of a synchronous client.

To run, invoke
    python3 -m websocket_server.examples.client WS-URL
where WS-URL is, e.g., ws://localhost:8080/echo if the server example
is running as well.
"""

import argparse

from ..client import connect

try: # Py2K
    raw_input
except NameError: # Py3K
    raw_input = input

def run_client(url):
    """
    Connect to the given WebSocket URL and pass messages between it and the
    console synchronously.
    """
    conn = connect(url)
    try:
        while 1:
            line = raw_input('> ')
            conn.write_text_frame(line)
            resp = conn.read_frame()
            if resp is None: break
            print ('< %s' % resp.content)
    except (EOFError, KeyboardInterrupt):
        print ('')
    finally:
        conn.close()

def main():
    """
    Run the example. See run_client() for the actual content.
    """
    p = argparse.ArgumentParser()
    p.add_argument('url', help='The WebSocket URL to connect to')
    arguments = p.parse_args()
    run_client(arguments.url)

if __name__ == '__main__': main()
