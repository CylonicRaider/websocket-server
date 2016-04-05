# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
Convenience functions for quick usage.
"""

import sys, os
import calendar
import hashlib
import optparse
import threading
import email.utils

from .compat import callable

try:
    from BaseHTTPServer import HTTPServer
except ImportError:
    from http.server import HTTPServer
try:
    from SocketServer import ThreadingMixIn
except ImportError:
    from socketserver import ThreadingMixIn

def parse_http_timestamp(date):
    return calendar.timegm(email.utils.parsedate(date))
def format_http_timestamp(ts):
    return email.utils.formatdate(ts, usegmt=True)

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """
    Multi-threaded HTTP server.

    Necessary for parallel use by many clients.
    """
    pass

class FileCache:
    """
    FileCache(webroot, cnttypes=None, **config) -> new instance

    Helper for caching and delivering static files.

    Constructor parameters:
    webroot : Base directory to resolve paths against, as a string. If
              callable, it is expected to produce Entries for the path
              given as the only positional argument.
    cnttypes: Mapping of filename extensions (with period) to MIME types.
              None (the default) is cast to an empty dictionary. Unless
              override_cnttypes is true, the class-level CNTTYPES
              attribute is merged to amend missing keys.

    Keyword-only parameters:
    merge_cnttypes: If true, the class attribute CNTTYPES will not be
                    considered while creating the content type mapping.

    Class attributes:
    CNTTYPES: Default content type mapping. Contains values for .txt,
              .html, .css, .js, and .ico files.
              NOTE: The mappings for .html and .txt include charset
                    specification clauses (both "charset=utf-8"). If
                    your files are not encoded in UTF-8, you can either
                    override the value, or remember that you live in
                    the third millenium.
    """

    CNTTYPES = {'.txt': 'text/plain; charset=utf-8',
                '.html': 'text/html; charset=utf-8',
                '.css': 'text/css',
                '.js': 'application/javascript',
                '.ico': 'image/vnd.microsoft.icon'}

    class Entry:
        """
        Entry(parent, path, data, updated=None, cnttype=None, source=None)
            -> new instance

        Entry of a FileCache.

        Constructor parameters:
        parent : The FileCache this Entry belongs to.
        path   : The (virtual) path of the file (like, /favicon.ico).
        data   : The data to be served as a byte string.
        updated: UNIX timestamp of the last update of the ressource, as a
                 floating-point number. Considered during etag calculation.
        cnttype: The content type to be used. None for "don't send".
        source : The (real) path of the file (if any; like,
                 /var/www/websockets/favicon.ico). If not present, validate()
                 assumes the ressource is virtual and does nothing.

        Instance variables (apart from constructor parameters):
        etag   : Entity tag. Unique identifier of the ressource in its
                 current state. Implemented as a hash of cnttype, updated,
                 and data.
        """

        @classmethod
        def read(cls, parent, path, source, cnttype=None, **kwds):
            """
            read(parent, path, source, cnttype=None, **kwds) -> Entry

            Read an Entry from a file. data and updated are automatically
            inferred derived from the file itself; further keyword arguments
            are passed through to the constructor. If cnttype is None, it
            is automatically inferred from the filename extension.
            """
            with open(source, 'rb') as f:
                try:
                    updated = os.fstat(f.fileno()).st_mtime
                except (IOError, TypeError):
                    updated = os.stat(source).st_mtime
                data = f.read()
            if cnttype is None:
                for k, v in parent.cnttypes.items():
                    if source.endswith(k):
                        cnttype = v
                        break
            return cls(parent, path, data, updated, cnttype, source, **kwds)

        def __init__(self, parent, path, data, updated=None, cnttype=None,
                     source=None):
            """
            __init__(parent, path, data, updated=None, cnttype=None,
                source=None) -> None

            See class docstring for details.
            """
            self.parent = parent
            self.path = path
            self.data = data
            self.updated = updated
            self.cnttype = cnttype
            self.source = source
            scnt, supd = str(cnttype), str(updated)
            self.etag = hashlib.md5(('%s,%s;%s,%s;' % (len(scnt), len(supd),
                scnt, supd)).encode('ascii')).update(data).hexdigest()

        def validate(self):
            """
            validate() -> Entry

            Verify that this Entry is still up-to-date, if not so, return
            a replacement, otherwise, return self.

            This should be called regularly to ensure the resource served
            is still up-to-date.
            """
            if self.source is not None:
                st = os.stat(self.source)
                if st.st_mtime != self.updated:
                    return self.read(self.parent, self.path, self.source,
                                     self.cnttype)
            return self

        def send(self, handler, force=False):
            """
            send(handler, force=False) -> None

            Deliver the data from the Entry to given BaseHTTPRequestHandler
            (or an instance of a subclass). Unless force is true, request
            headers are evaluated to decide whether a 304 Not Modified or
            a 200 OK should be sent.
            """
            send_full = True
            if not force:
                etag = handler.headers.get('If-None-Match')
                raw_timestamp = handler.headers.get('If-Modified-Since')
                timestamp = (None if raw_timestamp is None else
                             parse_http_timestamp(raw_timestamp))
                cached = (etag or raw_timestamp)
                etag_matches = (not etag or etag == self.etag)
                # HTTP timestamps don't have fractional seconds.
                timestamp_matches = (raw_timestamp is None or
                                     int(timestamp) == int(self.updated))
                if cached and etag_matches and timestamp_matches:
                    send_full = False
            if send_full:
                clen = len(self.data)
                handler.send_response(200, clen)
            else:
                clen = 0
                handler.send_response(304, clen)
            if self.cnttype:
                handler.send_header('Content-Type', self.cnttype)
            handler.send_header('Content-Length', clen)
            handler.send_header('ETag', self.etag)
            if self.updated:
                handler.send_header('Last-Modified',
                                    format_http_timestamp(self.updated))
            handler.end_headers()
            if send_full:
                handler.wfile.write(self.data)

    def __init__(self, webroot, cnttypes=None):
        """
        __init__(webroot, cnttypes=None) -> None

        See the class docstring for details.
        """
        self.webroot = webroot
        self.cnttypes = cnttypes
        self.entries = {}
        self.lock = threading.RLock()

    def __enter__(self):
        return self.lock.__enter__()
    def __exit__(self, *args):
        return self.lock.__exit__(*args)

    def get(self, path):
        """
        get(path) -> Entry

        Get an Entry for the given path. Either validate a cached one,
        or create a new one.
        """
        with self:
            ent = self.entries.get(path)
            if ent:
                ent = ent.validate()
            else:
                if callable(self.webroot):
                    ent = self.webroot()
                else:
                    source = path
                    if source[:1] in '/\\': source = source[1:]
                    source = os.path.join(self.webroot, source)
                    ent = self.Entry.read(self, path, source)
            self.entries[path] = ent
            return ent

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
