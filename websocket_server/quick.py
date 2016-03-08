# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
Convenience functions for quick usage.
"""

import sys
import optparse

try:
    from BaseHTTPServer import HTTPServer
except ImportError:
    from http.server import HTTPServer
try:
    from SocketServer import ThreadingMixIn
except ImportError:
    from socketserver import ThreadingMixIn

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """
    Multi-threaded HTTP server.

    Necessary for parallel use by many clients.
    """
    pass

def run(handler, server=ThreadingHTTPServer, prepare=None):
    """
    run(handler, server=ThreadingHTTPServer, prepare=None) -> None

    Actually run a WebSocket server instance.
    handler is the handler class to use,
    server  is a callable taking two arguments that creates the server
            instance; the arguments are:
            bindaddr: A (host, port) tuple containing the address to bind to.
                      Constructed from command-line arguments.
            handler : The request handler. Passed through from the same-named
                      argument of run().
    prepare is a callable that is invoked with the optparse.OptionParser
            instance used to parse options as the only argument. Can be used
            to specify additional options, it is up to the caller's
            discretion to distribute them to server or handler.
    """
    # Parse command-line arguments.
    p = optparse.OptionParser()
    p.add_option('-p', '--port', dest='port', type='int',
                 default=8080,
                 help='Specify the port to run on.',
                 metavar='PORT')
    p.add_option('--host', dest='host', default='',
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
        sys.stderr.write('Serving HTTP on port %s...\n' % options.port)
    sys.stderr.flush()
    # Run it.
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        # Don't print a noisy stack trace if Ctrl+C'ed.
        pass
