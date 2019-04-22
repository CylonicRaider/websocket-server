# websocket_server -- WebSocket/HTTP server/client library
# https://github.com/CylonicRaider/websocket-server

"""
Convenience functions for quick usage.
"""

import sys
import argparse

from .server import WebSocketMixIn
from .httpserver import ThreadingHTTPServer, RoutingRequestHandler
from .httpserver import validate_origin, parse_origin

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
    # Named function for better argparse output.
    def origin(s): return validate_origin(s)
    # Parse command-line arguments.
    p = argparse.ArgumentParser()
    p.add_argument('--port', '-p', metavar='PORT', type=int,
                   help='The TCP port to run on (defaults to the port from '
                       'the origin, or 8080).')
    p.add_argument('--host', '-s', metavar='IP',
                   help='The network interface to bind to (defaults to the '
                       'host from the origin, or any interface).')
    p.add_argument('--origin', '-O', type=origin,
                   help='A SCHEME://HOST[:PORT] string indicating how '
                       'clients should access this server. If omitted, '
                       'an attempt is made to guess the value from the '
                       '--host and --port parameters; if that fails, this '
                       'remains unset.')
    # Call preparation callback
    if prepare: prepare(p)
    # Actually parse arguments.
    arguments = p.parse_args()
    # Resolve complex defaults.
    if arguments.origin:
        _, host, port = parse_origin(arguments.origin)
        if arguments.host is None: arguments.host = host
        if arguments.port is None: arguments.port = port
    else:
        if arguments.host is None: arguments.host = ''
        if arguments.port is None: arguments.port = 8080
    # Create server.
    httpd = server((arguments.host, arguments.port), handler)
    if arguments.origin: httpd.origin = arguments.origin
    # Print header message.
    # Since the server has bound itself when it was contructed above, we can
    # insert the final origin value.
    if arguments.host:
        address = '%s:%s' % (arguments.host, arguments.port)
    else:
        address = '*:%s' % arguments.port
    origin_string = 'N/A' if httpd.origin is None else httpd.origin
    sys.stderr.write('Serving HTTP on %s (origin %s)...\n' % (address,
                                                              origin_string))
    sys.stderr.flush()
    # Call second preparation hook
    if premain: premain(httpd, arguments)
    # Run it.
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        # Don't print a noisy stack trace if Ctrl+C'ed.
        sys.stderr.write('\n')
