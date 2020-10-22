# websocket_server -- WebSocket/HTTP server/client library
# https://github.com/CylonicRaider/websocket-server

"""
WebSocket client implementation.
"""

import threading
import base64

from .ssl_compat import HAS_REAL_SSLCONTEXT as _HAS_REAL_SSLCONTEXT
from .ssl_compat import create_ssl_context
from .wsfile import client_handshake, wrap

try: # Py2K
    import httplib
    from urlparse import urlsplit, urlunsplit, urljoin
except ImportError: # Py3K
    import http.client as httplib
    from urllib.parse import urlsplit, urlunsplit, urljoin

__all__ = ['connect', 'create_connection']

if _HAS_REAL_SSLCONTEXT:
    http_connection = httplib.HTTPConnection
    https_connection = httplib.HTTPSConnection

else:
    # Backwards compatibility HACK
    class TweakHTTPSConnection(httplib.HTTPSConnection):
        """
        TweakHTTPSConnection(..., context=None) -> new instance

        Subclass of httplib.HTTPSConnection working around shortcomings of the
        standard library implementation.
        """

        def __init__(self, *args, **kwds):
            "Store away the SSL \"context\"."
            self.context = kwds.pop('context', None)
            httplib.HTTPSConnection.__init__(self, *args, **kwds)

        def connect(self):
            """
            Override the default behavior of SSL socket wrapping.

            In addition to a client certificate and a private key, this also
            allows passing a list of CA certificates, all via the "context".
            HTTPSConnection's own key_file and cert_file are ignored.
            """
            # Yes, we skip HTTPSConnection's implementation.
            httplib.HTTPConnection.connect(self)
            self.sock = self.context.wrap_socket(self.sock)

    http_connection = httplib.HTTPConnection
    https_connection = TweakHTTPSConnection

# HACK
class TweakHTTPResponse(httplib.HTTPResponse):
    """
    TweakHTTPResponse(...) -> new instance

    Subclass of httplib.HTTPResponse working around shortcomings of the
    standard library implementation.
    """

    def __init__(self, *args, **kwds):
        "Initialize lock."
        httplib.HTTPResponse.__init__(self, *args, **kwds)
        self._lock = threading.RLock()

    def begin(self):
        """
        Override the behavior of automatically closing 101 responses.

        Those are *meant* to be used further.
        """
        httplib.HTTPResponse.begin(self)
        if self.status == httplib.SWITCHING_PROTOCOLS:
            self.length = None
            self.will_close = True

    def read(self, amount=None):
        "Work around race condition between reading and closing."
        with self._lock:
            return httplib.HTTPResponse.read(self, amount)

    def readinto(self, buf):
        "Work around race condition between reading and closing."
        with self._lock:
            return httplib.HTTPResponse.readinto(self, buf)

    def close(self):
        "Work around race condition between reading and closing."
        with self._lock:
            return httplib.HTTPResponse.close(self)

def connect(url, protos=None, headers=None, cookies=None, ssl_config=None,
            **config):
    """
    connect(url, protos=None, headers=None, cookies=None, ssl_config=None,
            **config) -> WebSocketFile

    Connect to the given URL, which is parsed to obtain all necessary
    information. Depending on the scheme (ws or wss), a HTTPConnection or
    a HTTPSConnection is used internally. If the URL contains username or
    password fields, those will be sent as a Basic HTTP authentication
    header.
    protos (a list of strings, a string, or None) can be used to specify
    subprotocols. The server chooses a subprotocol (or none) from the list
    given by the client (where None counts as no subprotocols and the
    single-string form of the argument is interpreted as a comma-separated
    list). The subprotocol finally chosen (if any) is stored as the
    "subprotocol" instance attribute of the return value. See
    wsfile.client_handshake() for more details.
    headers can be None or a mapping of additional request headers to be
    added (NOTE that it is expected to implement the mutable mapping
    protocol and might be modified in-place).
    cookies can be a CookieJar instance from the websocket_server.cookies
    module, or anything that has compatible process_set_cookie() and
    format_cookie() methods; the latters are used to submit cookies with
    requests and to interpret the cookies returned with those. If cookies
    is omitted or None, cookies are not processed at all.
    ssl_config is a mapping containing "cert", "key", and/or "ca" keys,
    and is used to create an SSL context via the module-level
    create_ssl_context() function. If this is None instead, the default
    SSL behavior applies.
    Keyword arguments can be passed the underlying connection constructor
    via config.
    The URL connected to, the HTTP connection, and the HTTP response are
    stored in instance attributes of the return value, as "url",
    "request", and "response", respectively; the socket of the connection
    is available as "_socket".
    Raises a ValueError if the URL is invalid, or a ProtocolError if the
    remote host did not obey the protocol, a HTTPException if some
    HTTP-related error occurs (such as failure to authenticate or
    redirect), or whatever the underlying connection classes raise.
    """
    if headers is None: headers = {}
    # Allow connection reuse; prevent redirect loops.
    conn, connect_count = None, 32
    # Prepare SSL configuration.
    if ssl_config is not None:
        ssl_context = create_ssl_context(True, **ssl_config)
    else:
        ssl_context = None
    # Exceptions can occur anywhere.
    rdfile, wrfile = None, None
    try:
        # May need to follow redirections, autheticate, etc.
        while 1:
            # Check for redirect loops.
            if connect_count < 0:
                raise httplib.HTTPException('Redirect loop')
            connect_count -= 1
            # Split URL.
            purl = urlsplit(url)
            # Create connection.
            if conn:
                pass
            elif purl.scheme == 'ws':
                conn = http_connection(purl.hostname, purl.port, **config)
                conn.response_class = TweakHTTPResponse
                conn.connect()
            elif purl.scheme == 'wss':
                conn = https_connection(purl.hostname, purl.port,
                                        context=ssl_context, **config)
                conn.response_class = TweakHTTPResponse
                conn.connect()
            else:
                raise ValueError('Bad URL scheme.')
            # Initiate handshake.
            validate = client_handshake(headers, protos)
            # Cookies.
            if cookies is not None:
                v = cookies.format_cookie(url)
                if v: headers['Cookie'] = v
            # Send request.
            path = urlunsplit(('', '', purl.path, purl.query, ''))
            conn.putrequest('GET', path)
            for n, v in headers.items():
                conn.putheader(n, v)
            conn.endheaders()
            # Clean up old file, if any.
            try:
                wrfile.close()
            except Exception:
                pass
            # Grab socket reference; keep it alive for us.
            sock = conn.sock
            wrfile = sock.makefile('wb')
            # Obtain response.
            resp = conn.getresponse()
            # Cookies encore.
            if cookies is not None:
                # Could not find a cross-version way to select all headers
                # with a given name.
                setcookies = [v for k, v in resp.getheaders()
                              if k.lower() == 'set-cookie']
                for value in setcookies:
                    cookies.process_set_cookie(url, value)
            # Handle replies.
            if resp.status == httplib.SWITCHING_PROTOCOLS:
                break
            elif resp.status in (httplib.MOVED_PERMANENTLY, httplib.FOUND,
                                 httplib.SEE_OTHER,
                                 httplib.TEMPORARY_REDIRECT):
                # Redirection.
                loc = resp.getheader('Location')
                if not loc:
                    raise httplib.HTTPException('Missing redirection '
                        'location')
                # Allow relative locations.
                url = urljoin(url, loc)
                # Will possibly have to connect somewhere else.
                nres = urlsplit(url)
                if nres.hostname != purl.hostname or nres.port != purl.port:
                    conn.close()
                    conn = None
            elif resp.status == httplib.UNAUTHORIZED:
                # Basic HTTP authentication.
                auth = resp.getheader('WWW-Authenticate')
                if auth and not auth.startswith('Basic'):
                    raise httplib.HTTPException('Cannot authenticate')
                creds = (purl.username + ':' + purl.password).encode('utf-8')
                auth = 'Basic ' + base64.b64encode(creds).decode('ascii')
                headers['Authorization'] = auth
            else:
                raise httplib.HTTPException('Cannot handle status code %r' %
                                            resp.status)
        # Validate the response.
        p = validate(resp.msg)
        # Construct return value.
        # NOTE: Have to read from resp itself, as it might have buffered the
        #       beginning of the server's data, as those might have been
        #       coalesced with the headers.
        ret = wrap(resp, wrfile, subprotocol=p)
        ret.url = url
        ret._socket = sock
        ret.request = conn
        ret.response = resp
        return ret
    except:
        # Clean up connection
        for f in (conn, rdfile, wrfile):
            if not f: continue
            try:
                f.close()
            except IOError:
                pass
        raise

def create_connection(*args, **kwds):
    """
    create_connection(...) -> WebSocketFile

    An alias of connect(); see there for details.
    """
    return connect(*args, **kwds)
