# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
Convenience functions for quick usage.
"""

import sys
import optparse

from .server import WebSocketMixIn
from .httpserver import ThreadingHTTPServer, RoutingRequestHandler

__all__ = ['QuickRequestHandler', 'run']

class QuickRequestHandler(RoutingRequestHandler, WebSocketMixIn):
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
    prepare is a callable that is invoked with the OptionParser (from
            optparse) instance used to parse options as the only argument.
            Can be used to specify additional options.
    premain is called immediately before entering the main loop of the
            internally created server object with three arguments:
            httpd    : The server object created; an instance of server.
            options  : The options as returned by optparse.OptionParser.
            arguments: The arguments as returned by the latter.
            It can be used to pass on the values of the options configured
            using prepare to the server object and the handler class.
    """
    # Parse command-line arguments.
    p = optparse.OptionParser()
    p.add_option('-p', '--port', dest='port', type='int',
                 default=8080,
                 help='Specify the port to run on.',
                 metavar='PORT')
    p.add_option('-s', '--host', dest='host', default='',
                 help='Specify the network interface to bind to.',
                 metavar='IP')
    # Call preparation call-back
    if prepare: prepare(p)
    # Actually parse arguments.
    options, arguments = p.parse_args()
    # Create server.
    httpd = server((options.host, options.port), handler)
    # Print status message.
    if options.host:
        sys.stderr.write('Serving HTTP on %s:%s...\n' %
                         (options.host, options.port))
    else:
        sys.stderr.write('Serving HTTP on *:%s...\n' % options.port)
    sys.stderr.flush()
    # Call second preparation hook
    if premain: premain(httpd, options, arguments)
    # Run it.
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        # Don't print a noisy stack trace if Ctrl+C'ed.
        pass
