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

__all__ = ['run', 'FileCache']

def parse_http_timestamp(date):
    """
    parse_http_timestamp(date) -> float

    Parse a timestamp as present in HTTP headers. Return the corresponding
    UNIX time value.
    Convenience wrapper around email.utils.parsedate() and
    calendar.timegm().
    """
    return calendar.timegm(email.utils.parsedate(date))
def format_http_timestamp(ts):
    """
    format_http_timestamp(ts) -> str

    Format the given UNIX timestamp to a string as usable in HTTP headers.
    Convenience wrapper around email.utils.formatdate().
    """
    return email.utils.formatdate(ts, usegmt=True)

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """
    Multi-threaded HTTP server.

    Necessary for parallel use by many clients.
    Used by run().
    """
    pass

class FileCache:
    """
    FileCache(webroot, cnttypes=None, filter=None, **config)
        -> new instance

    Helper for caching and delivering static files.

    Constructor parameters (taken over as attributes):
    webroot : Base directory to resolve paths against, as a string; if a
              dictionary, expected to be a path-filename mapping similarly
              to the string option (relative filenames are resolved
              relative to the current working directory); if callable, it
              is expected to produce Entries for the path given as the
              only positional argument; the Ellipsis singleton may be
              returned to indicate that a path is actually a directory, or
              None if the path does not exist.
    cnttypes: Mapping of filename extensions (with period) to MIME types.
              None (the default) is cast to an empty dictionary. Unless
              override_cnttypes is true, the class-level CNTTYPES
              attribute is merged to amend missing keys.

    Keyword-only parameters:
    filter           : A callable or a container for whitelisting paths.
                       If callable, this is called before every access to
                       a resource with the virtual path as only argument
                       to determing whether the request is valid or should
                       be rejected; if not callable, a membership test
                       will be performed (like, path in filter) to
                       determine whether the access should be allowed;
                       this way, either a call-back or a precomputed list
                       can be specified. A filter of None (the default)
                       admits all paths.
    handle_dirs      : Handle directories. If true (as the default is),
                       access to directories is treated specially: If a
                       path that maps to a directory is requested, a
                       trailing slash (if not already present) is appended
                       by redirecting the client (temporarily), then a
                       file called "index.html" is delivered, instead of
                       the directory (if it exists). Because of the
                       redirecting, Entry.send() cannot be used for this,
                       and the send() method of FileCache must be used
                       (which implements this). If this is false, the
                       redirection does not happen, and send() treats
                       directories as absent.
    override_cnttypes: If true, the class attribute CNTTYPES will not be
                       considered while creating the content type mapping
                       (default is false; not taken over as an attribute).

    Other attributes:
    entries: A mapping of paths to Entry-s.
    lock   : A threading.RLock instance protecting entries. "with self"
             may be used instead.

    Class attributes:
    CNTTYPES: Default content type mapping. Contains values for .txt,
              .html, .css, .js, and .ico files.
              NOTE: The mappings for .html and .txt include charset
                    specification clauses (both "charset=utf-8"). If your
                    files are not encoded in UTF-8, you can either
                    override the value, or remember that you live in the
                    third millenium.
                    If you have somehow got this module into the past, you
                    are on your own.
    """

    CNTTYPES = {'.txt': 'text/plain; charset=utf-8',
                '.html': 'text/html; charset=utf-8',
                '.css': 'text/css',
                '.js': 'application/javascript',
                '.ico': 'image/vnd.microsoft.icon'}

    class Entry:
        """
        Entry(parent, path, data, updated=None, cnttype=None, source=None,
              **kwds) -> new instance

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

        Extra keyword arguments are ignored.

        Instance variables (apart from constructor parameters):
        etag: Entity tag. Unique identifier of the ressource in its current
              state. Implemented as a hash of cnttype, updated, and data.
        """

        @classmethod
        def read(cls, parent, path, source, cnttype=None, **kwds):
            """
            read(parent, path, source, cnttype=None, **kwds) -> Entry

            Read an Entry from a file. data and updated are automatically
            inferred derived from the file itself; further keyword arguments
            are passed through to the constructor. If cnttype is None, it is
            automatically inferred from the filename extension.
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
                     source=None, **kwds):
            """
            __init__(parent, path, data, updated=None, cnttype=None,
                     source=None, **kwds) -> None

            See class docstring for details.
            """
            self.parent = parent
            self.path = path
            self.data = data
            self.updated = updated
            self.cnttype = cnttype
            self.source = source
            scnt, supd = str(cnttype), str(updated)
            h = hashlib.md5(('%s,%s;%s,%s;' % (len(scnt), len(supd),
                scnt, supd)).encode('ascii'))
            h.update(data)
            self.etag = h.hexdigest()

        def validate(self):
            """
            validate() -> Entry

            Verify that this Entry is still up-to-date, if not so, return a
            replacement, otherwise, return self.

            This should be called regularly to ensure the resource served is
            still up-to-date.
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
            headers are evaluated to decide whether a 304 Not Modified or a
            200 OK should be sent.
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
                handler.send_response(200)
            else:
                clen = 0
                handler.send_response(304)
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

    def __init__(self, webroot, cnttypes=None, **config):
        """
        __init__(webroot, cnttypes=None, **config) -> None

        See the class docstring for details.
        """
        if cnttypes is None: cnttypes = {}
        self.webroot = webroot
        self.cnttypes = cnttypes
        self.filter = config.get('filter', None)
        self.handle_dirs = config.get('handle_dirs', True)
        self.entries = {}
        if not config.get('override_cnttypes'):
            for k, v in self.CNTTYPES.items():
                self.cnttypes.setdefault(k, v)
        self.lock = threading.RLock()

    def __enter__(self):
        return self.lock.__enter__()
    def __exit__(self, *args):
        return self.lock.__exit__(*args)

    def get(self, path, **kwds):
        """
        get(path, **kwds) -> Entry or Ellipsis or None

        Get an Entry for the given path. Either validate a cached one, or
        create a new one. If the path does not pass self.filter, None is
        returned without performing any further action. If the path is
        pointing to a directory (as determined by filesystem inspection or
        the callable self.webroot), Ellipsis is returned. Keyword
        arguments are passed to either self.webroot (if that is called),
        or to the class-level read() method.
        """
        if self.filter is None:
            pass
        elif callable(self.filter):
            if not self.filter(path): return None
        else:
            if path not in self.filter: return None
        with self:
            ent = self.entries.get(path)
            if ent and ent is not Ellipsis:
                ent = ent.validate()
            elif callable(self.webroot):
                ent = self.webroot(path, **kwds)
            else:
                if isinstance(self.webroot, dict):
                    try:
                        source = self.webroot[path]
                    except KeyError:
                        return None
                else:
                    source = path
                    if source[:1] in ('/', os.sep):
                        source = source[1:]
                    nwr = os.path.normpath(os.path.join(self.webroot,
                                                        os.sep))
                    source = os.path.normpath(os.path.join(nwr, source))
                    if not source.startswith(nwr):
                        return None
                if os.path.isdir(source):
                    ent = Ellipsis
                elif os.path.isfile(source):
                    ent = self.Entry.read(self, path, source, **kwds)
                else:
                    ent = None
            self.entries[path] = ent
            return ent

    def send(self, handler, path=None, **kwds):
        """
        send(handler, path=None, **kwds) -> Entry or Ellipsis or None

        Send the resource named by path to handler. If path is None, the
        handler's path attribute (minus the query) is used.
        Directories are handled if the handle_dirs attribute is true; see
        the description in the class docstring for details.
        Keyword arguments are passed through to the get() method.
        The return value is an Entry if a page was served successfully,
        Ellipsis if an automatic redirection happened, or None if nothing
        could be done (the caller might serve a 404 page instead).
        """
        if path is None: path = handler.path.partition('?')[0]
        res = self.get(path, **kwds)
        if not res:
            return res
        elif res is Ellipsis:
            if not self.handle_dirs: return None
            if not path.endswith('/'):
                handler.send_response(302)
                handler.send_header('Location', path + '/')
                handler.send_header('Content-Length', 0)
                handler.end_headers()
                return Ellipsis
            path += 'index.html'
            res = self.get(path, **kwds)
            if not res:
                return res
            elif res is Ellipsis:
                # Seriously? You named a directory "index.html"?
                return None
        res.send(handler)
        return res

def run(handler, server=ThreadingHTTPServer, prepare=None):
    """
    run(handler, server=ThreadingHTTPServer, prepare=None) -> None

    Actually run a WebSocket server instance.
    handler is the handler class to use,
    server  is a callable taking two arguments that creates the server
            instance; the arguments are:
            bindaddr: A (host, port) tuple containing the address to bind
                      to. Constructed from command-line arguments.
            handler : The request handler. Passed through from the same-
                      named argument of run().
    prepare is a callable that is invoked with the OptionParser (from
            optparse) instance used to parse options as the only argument.
            Can be used to specify additional options; it is up to the
            caller's discretion to distribute the values to server or
            handler.
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
