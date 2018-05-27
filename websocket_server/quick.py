# websocket_server -- WebSocket/HTTP server/client library
# https://github.com/CylonicRaider/websocket-server

"""
Convenience functions for quick usage.
"""

import sys
import argparse

from .server import WebSocketMixIn
from .httpserver import ThreadingHTTPServer, RoutingRequestHandler

__all__ = ['RoutingWebSocketRequestHandler', 'run']

class RoutingWebSocketRequestHandler(RoutingRequestHandler, WebSocketMixIn):
    """
    An HTTP request handler combining all the package's functionality.
    """

def run(handler, server=ThreadingHTTPServer, prepare=None, premain=None):
    """
    run(handler, server=ThreadingHTTPServer, prepare=None, premain=None)
        -> None

    Actually run a WebSocket server instance.
    handler is the handler class to use.
    server  is a callable taking two arguments that creates the server
            instance; the arguments are:
            bindaddr: A (host, port) tuple containing the address to bind
                      to. Constructed from command-line arguments.
            handler : The request handler. Passed through from the same-
                      named argument of run().
    prepare is a callable that is invoked with the ArgumentParser (from
            argparse) instance used to parse options as the only argument.
            Can be used to specify additional options.
    premain is called immediately before entering the main loop of the
            internally created server object with two arguments:
            httpd    : The server object created; an instance of server.
            arguments: The arguments as returned by argparse.ArgumentParser.
            It can be used to pass on the values of the options configured
            using prepare to the server object and the handler class.
    """
    # Parse command-line arguments.
    p = argparse.ArgumentParser()
    p.add_argument('--port', '-p', metavar='PORT', type=int, default=8080,
                   help='Specify the port to run on.')
    p.add_argument('--host', '-s', metavar='IP', default='',
                   help='Specify the network interface to bind to.')
    # Call preparation callback
    if prepare: prepare(p)
    # Actually parse arguments.
    arguments = p.parse_args()
    # Create server.
    httpd = server((arguments.host, arguments.port), handler)
    # Print status message.
    if arguments.host:
        sys.stderr.write('Serving HTTP on %s:%s...\n' %
                         (arguments.host, arguments.port))
    else:
        sys.stderr.write('Serving HTTP on *:%s...\n' % arguments.port)
    sys.stderr.flush()
    # Call second preparation hook
    if premain: premain(httpd, arguments)
    # Run it.
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        # Don't print a noisy stack trace if Ctrl+C'ed.
        sys.stderr.write('\n')
