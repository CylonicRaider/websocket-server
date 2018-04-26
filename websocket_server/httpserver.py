# websocket_server -- WebSocket/HTTP server/client library
# https://github.com/CylonicRaider/websocket-server

"""
Convenience extensions for the standard library's HTTP server framework.

The classes in this module implement support for static file retrieval,
advanced logging, query string / POST submission parsing, cookies, and
request routing.
"""

import sys, os, re, time
import errno
import cgi
import hashlib
import threading

from .compat import callable, unicode
from .cookies import RequestHandlerCookies
from .tools import format_http_date, parse_http_date, htmlescape, FormData

try: # Py2K
    from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
    from SocketServer import ThreadingMixIn
except ImportError: # Py3K
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from socketserver import ThreadingMixIn

__all__ = ['HTTPError', 'FileCache', 'callback_producer',
           'HTTPRequestHandler', 'RoutingRequestHandler', 'RouteSet']

WILDCARD_RE = re.compile(r'<([a-zA-Z_][a-zA-Z0-9_]*)>|\\(.)')
ESCAPE_RE = re.compile(r'[\0-\x1f \\]')
ESCAPE_INNER_RE = re.compile(r'[\0- \\"]')
QUOTE_RE = re.compile(r'[\0-\x1f\\"]')

REDIRECT_BODY = '''\
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8"/>
    <title>Redirect</title>
  </head>
  <body>
    <h1>%(title)s</h1>
    <p>Please continue <a href="%(url)s">here</a>.</p>
  </body>
</html>
'''

class HTTPError(Exception):
    """
    HTTPError(code, desc=None) -> new instance

    Exceptions of this type may be raised by RoutingRequestHandler callbacks
    to force a particular HTTP response. code is the HTTP status code to
    transmit; desc is an optional string giving detail on the exact reason
    of the error; see RoutingRequestHandler.send_code() for the layout of the
    response body.

    The "code" and "desc" attributes hold the values of the corresponding
    constructor arguments.
    """

    def __init__(self, code, desc=None):
        """
        __init__(code, desc=None) -> None

        Instance initializer; see class docstring for details.
        """
        Exception.__init__(self, 'HTTP code %s%s' % (code,
            ': %s' % desc if desc else ''))
        self.code = code
        self.desc = desc

def normalize_path(path):
    """
    normalize_path(path) -> str

    This makes a "normalize" relative path out of path, suitable to be
    safely joined with some directory path.
    path is first made absolute (by prepending os.path.sep), then
    os.path.normpath() is applied, after which the path is made relative
    (by removing all leading parent directory references).
    """
    path = os.path.normpath(os.path.sep + path)
    # *Should* run only once...
    while path.startswith(os.path.sep):
        path = path[len(os.path.sep):]
    return path

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """
    Multi-threaded HTTP server.

    Necessary for parallel use by many clients. Used by the quick module.
    """

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
              is expected to produce Entries for self and the path given
              as positional arguments; the Ellipsis singleton may be
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
    append_html      : If a file is absent and this is true (as the default
                       is not), FileCache.send() tries delivering the file
                       with the ".html" suffix appended to the name before
                       failing. Although this could be implemented in
                       Entry.send(), it is in FileCache.send() for symmetry
                       with handle_dirs. Can be used to provide "action
                       paths" (such as "/login") whilst keeping semantic
                       file extensions.
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
                             parse_http_date(raw_timestamp))
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
                                    format_http_date(self.updated))
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
        self.append_html = config.get('append_html', False)
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
                ent = self.webroot(self, path, **kwds)
            else:
                if isinstance(self.webroot, dict):
                    try:
                        source = self.webroot[path]
                    except KeyError:
                        return None
                else:
                    source = normalize_path(path)
                    source = os.path.join(self.webroot, source)
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
            if not self.append_html: return None
            path += '.html'
            res = self.get(path, **kwds)
            if not res:
                return None
            elif res is Ellipsis:
                # Seriously? You have a directory with a name ending with
                # ".html"?
                return None
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
                # See above for oddly named directories.
                return None
        res.send(handler)
        return res

    def __call__(self, handler, path=None):
        """
        self(handler, path=None) -> bool

        This allows FileCache instances to be used as "callbacks" in
        RouteSet-s. The arguments are passed on to send(); the return
        value is adjusted to achieve the desired behavior.
        """
        return (not self.send(handler, path))

def callback_producer(callback, base='', guess_type=True):
    """
    callback_producer(callback, base='', guess_type=True) -> function

    The returns a callable suitable as a webroot for FileCache that uses
    callback to obtain the data for a given path and wraps them in an
    FileCache.Entry.
    callback is called with the path as the only argument, and is expected
    to return a byte string containing the data to deliver. If callback
    returns None or Ellipsis or an Entry instance, those are passed
    through; if it raises an IOError, a EISDIR is translated to an
    Ellipsis return value, and all other exceptions result in a None
    return. MIME type guessing is performed (basing on the path) if
    guess_type is true. Since the Entry is not actually tied to a
    filesystem object (as far as we know), its source attribute is None.
    If base is None, the path is passed without modification, otherwise,
    it is normalized first (see normalize_path()) and joined with base; if
    base is the empty string, the path is effectively only normalized.
    """
    def produce(parent, path):
        """
        produce(parent, path) -> FileCache.Entry

        Callback-based Entry producer for FileCache. See callback_producer()
        for details.
        """
        if base is not None:
            path = os.path.join(base, normalize_path(path))
        try:
            data = callback(path)
        except IOError as e:
            if e.errno == errno.EISDIR:
                return Ellipsis
            else:
                return None
        if data in (None, Ellipsis) or isinstance(data, FileCache.Entry):
            return data
        if guess_type:
            for k, v in parent.cnttypes.items():
                if path.endswith(k):
                    cnttype = v
                    break
            else:
                cnttype = None
        else:
            cnttype = None
        return FileCache.Entry(parent, path, data, time.time(), cnttype)
    return produce

class HTTPRequestHandler(BaseHTTPRequestHandler):
    """
    An HTTP request handler with additional convenience functions.

    To enable advanced logging, set the _log_data attribute to a new
    dictionary in the setup() method. The following keys are of significance:
    userid: The identity of the user submitting the request as a string. Not
            set by HTTPRequestHandler, but might be set by user code.
    code  : The HTTP status code. Set in log_request().
    size  : The HTTP response size. Set in log_request() and send_header().
    extra : Extra data as a mapping. The keys must be strings while the
            values' str() representation should be something meaningful.
    To use cookies, override the cookie_descs() method to return a mapping of
    cookie descriptions (not overriding it will work as well, but no cookies
    will be captured from the request in that case), and use the cookies
    attribute.
    To conveniently access query strings and POSTed HTML forms, use the
    getvars and postvars attributes.
    NOTE that these cannot deal with uploads of large files.
    """

    def setup(self):
        """
        setup() -> None

        Perform instance initialization.
        """
        BaseHTTPRequestHandler.setup(self)
        self._log_data = None
        self._cookies = None
        self._getvars = None
        self._postvars = None

    def log_request(self, code='-', size='-'):
        """
        log_request(code='-', size='-') -> None

        Log an HTTP request, using the given code and response size. This
        implementation can behave in two ways:
        - If the _log_data attribute is set to None, the parent class'
          method is called, and nothing else happens.
        - Otherwise (_log_data must be a dictionary in that case), the code
          and response size are stored in it and logging the request is
          withheld to be able to capture more data. Call really_log_request()
          to really log the request.
        """
        if self._log_data is None:
            return BaseHTTPRequestHandler.log_request(self, code, size)
        code = None if code == '-' else int(code)
        size = None if size == '-' else int(size)
        self._log_data.update(code=code, size=size)

    def send_header(self, name, value):
        """
        send_header(name, value) -> None

        Send an HTTP header. This method forwards to the parent class, and
        also captures Content-Length headers if advanced logging is enabled.
        """
        BaseHTTPRequestHandler.send_header(self, name, value)
        if self._log_data is not None and name.lower() == 'content-length':
            self._log_data['size'] = value

    def really_log_request(self):
        """
        really_log_request() -> None

        Log an HTTP request using an extended format. If the _log_data
        attribute is None, this does nothing (assuming that the request has
        already been logged); this method sets it to None to allow multiple
        invocations to produce only one log entry.
        """
        def makehex(m):
            return r'\x%02x' % ord(m.group())
        def escape(s):
            if s is None: return '-'
            return ESCAPE_RE.sub(makehex, s)
        def escape_inner(s):
            return ESCAPE_INNER_RE.sub(makehex, s)
        def escape_int(s):
            try:
                return str(int(s))
            except (TypeError, ValueError):
                return '-'
        def quote(s):
            if s is None: return '-'
            return '"' + QUOTE_RE.sub(makehex, s) + '"'
        if self._log_data is None: return
        extradata = self._log_data.get('extra')
        if extradata:
            extra = ' "' + ' '.join(escape_inner(k) + '=' +
                escape_inner(str(v)) for k, v in extradata.items()) + '"'
        else:
            extra = ''
        sys.stderr.write('%s - %s [%s] %s %s %s %s %s%s\n' % (
            self.client_address[0], escape(self._log_data.get('userid')),
            self.log_date_time_string(), quote(self.requestline),
            escape_int(self._log_data.get('code')),
            escape_int(self._log_data.get('size')),
            quote(self.headers.get('Referer')),
            quote(self.headers.get('User-Agent')), extra))
        sys.stderr.flush()
        self._log_data = None

    def cookie_descs(self):
        """
        cookie_descs() -> dict

        Return a mapping of cookie descriptions. See RequestHandlerCookies
        for details.
        """
        return {}

    @property
    def cookies(self):
        """
        cookies -> RequestHandlerCookies

        A mapping-like object containing cookies for this request.
        On the first access, the property is initialized from the request;
        thereafter, the same cached object is returned. It may be modified
        in-place. To submit the (possibly modified) cookies with the
        response, invoke the send() method of the cookies object while
        sending headers.
        """
        if self._cookies is not None: return self._cookies
        self._cookies = RequestHandlerCookies(self, self.cookie_descs())
        self._cookies.load()
        return self._cookies

    @property
    def getvars(self):
        """
        getvars -> FormData

        A mapping-like object containing the query string of this request
        in decomposed form.
        """
        if self._getvars is not None: return self._getvars
        self._getvars = FormData.from_qs(self.path.partition('?')[2])
        return self._getvars

    @property
    def postvars(self):
        """
        postvars -> FormData

        If the request contains HTML form data as the request body, this
        contains them in a decomposed form; otherwise, this attribute is
        an empty FormData instance (as determinable by a truth value test).
        """
        if self._postvars is not None: return self._postvars
        try:
            ctype, pdict = cgi.parse_header(self.headers.get('Content-Type'))
            if ctype == 'multipart/form-data':
                data = cgi.parse_multipart(self.rfile, pdict)
                self._postvars = FormData.from_dict(data)
            elif ctype == 'application/x-www-form-urlencoded':
                if 'Content-Length' in self.headers:
                    l = int(self.headers['Content-Length'])
                    data = self.rfile.read(l)
                else:
                    data = self.rfile.read()
                self._postvars = FormData.from_qs(data)
            else:
                raise Exception
        except Exception:
            self._postvars = FormData()
        return self._postvars

    def _code_phrase(self, code):
        """
        _code_phrase(code) -> str

        Map a HTTP status code to a string matching the following pattern:
        "<CODE> <PHRASE>", e.g. "200 OK".
        """
        phrase, _ = self.responses.get(code, ('???', None))
        return '%s %s' % (code, phrase)

    def send_text(self, code, text, cnttype=None, cookies=False):
        """
        send_text(code, text, cnttype=None, cookies=False) -> None

        Send a complete minimal HTTP response. code is the HTTP status code
        to use (e.g. 200 or 404), text is the response body to send, cnttype
        is the MIME type to use (defaulting to text/plain), cookies specifies
        whether cookies should be sent along with the response.
        text is either a single string or a sequence of things which are
        formatted and concatenated to obtain the final response. Valid things
        are the None singleton (which is ignored), Unicode strings (which are
        encoded using UTF-8), byte strings (which are used without
        modification), and exception objects (which are formatted similarly
        to the built-in exception formatter, without tracebacks).
        """
        if cnttype is None: cnttype = 'text/plain; charset=utf-8'
        if isinstance(text, (str, unicode, bytes)): text = (text,)
        parts = []
        for t in text:
            if t is None:
                continue
            elif isinstance(t, (str, unicode)):
                parts.append(t.encode('utf-8'))
            elif isinstance(t, bytes):
                parts.append(t)
            elif isinstance(t, BaseException):
                s = '%s: %s' % (t.__class__.__name__, t)
                parts.append(s.encode('utf-8'))
            else:
                raise TypeError('Cannot handle %r as text' % (t,))
        enctext = b''.join(parts)
        self.send_response(code)
        self.send_header('Content-Type', cnttype)
        self.send_header('Content-Length', len(enctext))
        if cookies: self.cookies.send()
        self.end_headers()
        self.wfile.write(enctext)

    def send_redirect(self, code, target, send_text=True, cookies=False):
        """
        send_redirect(code, target, send_text=True, cookies=False) -> None

        Send a complete mimimal HTTP redirect response. code is the status
        code to use (e.g. 303), target is the URL to redirect to, send_text
        determines whether a minimal HTML response body is sent, cookies
        specifies whether cookies should be sent along with the response.
        """
        if send_text:
            body = (REDIRECT_BODY % {
                'title': htmlescape(self._code_phrase(code)),
                'url': htmlescape(target)}).encode('utf-8')
        else:
            body = b''
        self.send_response(code)
        self.send_header('Location', target)
        if body: self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        if cookies: self.cookies.send()
        self.end_headers()
        self.wfile.write(body)

class RoutingRequestHandler(HTTPRequestHandler):
    """
    An HTTP request handler providing sophisticated routing capabilities.

    This class intercepts all do_*() methods (if not explicitly defined by a
    child class), provides a bunch of convenience methods for sending common
    HTTP responses, and overrides the default error handler to match the
    latters' style.
    This class enables HTTPRequestHandler's advanced logging by default; the
    "extra" key is initialized to an empty dictionary, which can be used
    immediately.

    The "routes" attribute should be set on subclasses or instances of this,
    or all HTTP requests will be responded to with 500's.
    """

    routes = None

    def __getattr__(self, name):
        "Hack to capture HTTP requests regardless of method."
        if name.startswith('do_'):
            return self.handle_request
        raise AttributeError(name)

    def setup(self):
        """
        setup() -> None

        Perform instance initialization.
        """
        HTTPRequestHandler.setup(self)
        self._log_data = {'extra': {}}

    def end_headers(self):
        """
        end_headers() -> None

        Finish submitting headers. This implementation additionally writes
        out an advanced log entry.
        """
        HTTPRequestHandler.end_headers(self)
        self.really_log_request()

    def send_code(self, code, message=None):
        """
        send_code(code, message=None) -> None

        Send a response with code as the status code and the following
        plain-text body:

            <CODE> <PHRASE>
            <MESSAGE>

        where <CODE> is code (e.g., 400), <PHRASE> is the verbal description
        of the code (e.g., "Bad Request"), and <MESSAGE> is message (e.g.,
        "Missing required header field.").
        """
        phrase, _ = self.responses.get(code, ('???', None))
        self.send_text(code, (str(code), ' ', phrase,
                              '\n' if message else '', message))

    def send_200(self, text=None):
        "Send an OK response; see send_code()."
        self.send_code(200, text)
    def send_400(self, text=None):
        "Send a Bad Request response; see send_code()."
        self.send_code(400, text)
    def send_403(self, text=None):
        "Send a Forbidden response; see send_code()."
        self.send_code(403, text)
    def send_404(self, text=None):
        "Send a Not Found response; see send_code()."
        self.send_code(404, text)
    def send_405(self, text=None):
        "Send a Method Not Allowed response; see send_code()."
        self.send_code(405, text)
    def send_500(self, text=None):
        "Send an Internal Server Error response; see send_code()."
        self.send_code(500, text)

    def send_cache(self, entry):
        """
        send_cache(entry) -> None

        Send an entry of a FileCache, or a 404 page is entry is None.
        """
        if entry is not None:
            entry.send(self)
        else:
            self.send_404()

    def send_error(self, code, message=None):
        """
        send_error(code, message=None) -> None

        Send and log an error reply. This overrides the same-named parent
        class' method to provide a style consistent with the send_*()
        convenience methods.
        """
        self.log_error('code %d, message %s', code, message)
        if self.command != 'HEAD' and code >= 200 and code not in (204, 205,
                                                                   304):
            self.send_code(code, message)
        else:
            self.send_text(code, '')

    def handle_request(self):
        """
        handle_request() -> None

        Actually handle a request by matching it to a route and invoking the
        corresponding callback; see RouteSet for details. HTTPError
        exceptions are caught and processed using send_code(). Other
        exceptions are passed to the handle_exception() method.
        """
        try:
            res = self.routes.get(self.command, self.path)
            if res:
                func, kwds = res
                res = (not func(self, **kwds))
            if not res:
                self.handle_fallback()
        except HTTPError as e:
            self.send_code(e.code, e.desc)
        except Exception as e:
            self.handle_exception(e)
        finally:
            self.really_log_request()

    def handle_exception(self, exc):
        """
        handle_exception(exc) -> None

        Handle an exception that was raised while handling a request. The
        default implementation logs the exception and returns a plain 500
        response.
        """
        self.log_error('%r', exc)
        self.send_500()

    def handle_fallback(self):
        """
        handle_fallback() -> None

        Handle a request that no route matched. The default implementation
        responds to GET requests with a 404 and to all other requests with
        a 405.
        """
        if self.command == 'GET':
            self.send_404()
        else:
            self.send_405()

class RouteSet:
    """
    RouteSet(fixroutes=None, dynroutes=None, fbfunc=None) -> new instance

    A set of routes for a RoutingRequestHandler. fixroutes is a mapping from
    (method, path) pairs to functions to be invoked by the request handler.
    dynroutes is a mapping from request methods to lists of (regex, cb)
    pairs; for each request, after considering fixed routes, the list
    corresponding to the request method is retrieved, and iterated through
    until a regular expression is found that matches the request's path; the
    function corresponding to it is invoked. fbfunc is the fallback function
    to be invoked when neither fixed nor dynamic routes matched.

    Callbacks are invoked with the RoutingRequestHandler instance as an
    explicit first positional argument, and, for dynamic routes, with the
    named groupings of the regex as keyword arguments. By returning a true
    value, a callback communicates that it did *not* handle the request, and
    fallback behavior should be applied (in particular, a return value of
    None inhibits the fallback behavior).

    The "fixroutes", "dynroutes", and "fbfunc" instance attributes contain
    the values of the corresponding constructor parameters, and are modified
    in-place by add() etc.

    Instances of this class can be used as decorators, as illustrated below:
    >>> route = RouteSet()
    >>> @route('/hello')
    ... def handle_hello(self):
    ...     ... # handle GET requests to /hello
    ...
    >>> @route('/invite/<code>', 'POST')
    ... def handle_invite(self, code):
    ...     ... # handle POST requests to /invite/*
    ...
    >>> @route.fallback
    ... def handle_fallback(self):
    ...     ... # handle any requests not matched above
    ...
    >>> RequestHandler = route.build(RoutingRequestHandler)
    """

    def __init__(self, fixroutes=None, dynroutes=None, fbfunc=None):
        """
        __init__(fixroutes=None, dynroutes=None, fbfunc=None) -> None

        Instance initializer; see the class docstring for details.
        """
        if fixroutes is None: fixroutes = {}
        if dynroutes is None: dynroutes = {}
        self.fixroutes = fixroutes
        self.dynroutes = dynroutes
        self.fbfunc = fbfunc

    def __copy__(self):
        """
        __copy__() -> RouteSet

        Return a shallow copy of this instance.
        """
        return self.copy()

    def copy(self):
        """
        copy() -> RouteSet

        Return a copy of this instance.
        """
        return RouteSet(dict(self.fixroutes),
                        dict((k, list(v)) for k, v in self.dynroutes),
                        self.fbfunc)

    def add(self, func, path, method='GET'):
        """
        add(func, path, method='GET') -> None

        Add a new route to the route set. func is the callback to invoke (see
        the class docstring for details); path is the path template to match
        (see below); method is the request method to match (note that
        matching is case-sensitive).

        path may contain "wildcards" following the "<NAME>" pattern (where
        NAME is an identifier), and escape sequences consisting of a
        backslash followed by a less-than sign (<). Using less-than signs or
        backslashes in ways other than described here is not specified and
        the behavior can change incompatibly in the future.
        If a wildcard or escape sequence is present, the route automatically
        becomes dynamic; each wildcard matches a "path component" (i.e. a
        sequence of characters not containing slashes or question marks),
        and the matched path component is passed to the callback as a named
        argument (with the name taken from the wildcard).
        """
        pos, wildcards, regex = 0, False, ['^']
        while 1:
            m = WILDCARD_RE.search(path, pos)
            if not m: break
            wildcards = True
            regex.append(re.escape(path[pos:m.start()]))
            if m.group(1) is not None:
                regex.append(r'(?P<%s>[^/?]+)' % m.group(1))
            else:
                regex.append(re.escape(m.group(2)))
            pos = m.end()
        if wildcards:
            regex.append(path[pos:])
            regex.append('$')
            regex = re.compile(''.join(regex))
            self.dynroutes.setdefault(method, []).append((regex, func))
        else:
            self.fixroutes[method, path] = func

    def fallback(self, func):
        """
        fallback(func) -> None

        Make func the fallback function of this route set.
        """
        self.fbfunc = func
        return func

    def get(self, method, path):
        """
        get(method, path) -> (function, dict) or None

        Retrieve a callback to be invoked to handle a request to path and
        keyword arguments to pass to it, or None if no route matches.
        """
        path = path.partition('?')[0]
        try:
            return (self.fixroutes[method, path], {})
        except KeyError:
            for r in self.dynroutes.get(method, ()):
                m = r[0].match(path)
                if m: return (r[1], m.groupdict())
        if self.fbfunc is not None: return (self.fbfunc, {})
        return None

    def build(self, baseclass, namespace=None):
        """
        build(baseclass, namespace=None) -> type

        Return a newly created subclass of baseclass (which should be
        RoutingRequestHandler or a child class) configured to serve requests
        using the routes contained in this instance. If namespace is not
        None, it must be a mapping containing class variables to set on the
        returned class; it is amended (out-of-place) by a "routes" key mapped
        to this instance.
        """
        if namespace is None:
            namespace = {'routes': self}
        else:
            namespace = dict(namespace, routes=self)
        return type('<anonymous>', (baseclass, object), namespace)

    def __call__(self, *args, **kwds):
        """
        self(...) -> function

        This is a convenience wrapper around add() that allows the use of
        this instance as a decorator. The returned function takes a single
        argument, and passes it, followed by all arguments to this function,
        on to add(), and returns the function it was passed.
        """
        def callback(func):
            self.add(func, *args, **kwds)
            return func
        return callback
