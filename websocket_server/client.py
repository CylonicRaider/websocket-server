# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
Client-side support.

Although this is supposed to be a "server" module, client-side support is
quite a low-hanging fruit.
"""

import os
import threading
import base64

from .exceptions import ProtocolError
from .wsfile import wrap
from .server import process_key

try:
    import httplib
except ImportError:
    import http.client as httplib
try:
    from urlparse import urlsplit, urlunsplit, urljoin
except ImportError:
    from urllib.parse import urlsplit, urlunsplit, urljoin

__all__ = ['connect']

# HACK
class TweakHTTPResponse(httplib.HTTPResponse):
    """
    TweakHTTPResponse(...) -> new instance

    Subclass of httplib.HTTPResponse working around shortcomings of the
    standard library implementation.
    """

    def __init__(self, *args, **kwds):
        "Initialize lock"
        httplib.HTTPResponse.__init__(self, *args, **kwds)
        self._lock = threading.RLock()

    def begin(self):
        """
        Override the behavior of automatically closing 101 responses

        Those are *meant* to be used further.
        """
        httplib.HTTPResponse.begin(self)
        if self.status == httplib.SWITCHING_PROTOCOLS:
            self.length = None
            self.will_close = True

    def read(self, amount=None):
        "Work around race condition between reading and closing"
        with self._lock:
            return httplib.HTTPResponse.read(self, amount)

    def readinto(self, buf):
        "Work around race condition between reading and closing"
        with self._lock:
            return httplib.HTTPResponse.readinto(self, buf)

    def close(self):
        "Work around race condition between reading and closing"
        with self._lock:
            return httplib.HTTPResponse.close(self)

def connect(url, protos=None, headers=None, cookies=None, **config):
    """
    connect(url, protos=None, headers=None, cookies=None, **config)
        -> WebSocketFile

    Connect to the given URL, which is parsed to obtain all necessary
    information. Depending on the scheme (ws or wss), a HTTPConnection or
    a HTTPSConnection is used internally. If the URL contains username or
    password fields, those will be sent as a Basic HTTP authentication
    header.
    protos (a list of strings, a string, or None) can be used to specify
    subprotocols.
    headers can be None or a mapping of additional request headers to be
    added (note that it is expected to implement the mutable mapping
    protocol and will be modified).
    cookies can be a CookieJar instance from the websocket_server.cookies
    module, or anything that has compatible process_set_cookie() and
    format_cookie() methods; the latters are used to submit cookies with
    requests and to interpret the cookies returned with those. If cookies
    is omitted or None, cookies are not processed at all.
    Keyword arguments can be passed the underlying connection constructor
    via config.
    The HTTP connection and response are stored in instance attributes of
    the return value, as "request" and "response", respectively; the
    socket of the connection is available as "_socket".
    Raises a ValueError if the URL is invalid, or a ProtocolError if the
    remote host did not obey the protocol, a HTTPException if some HTTP-
    related error occurs (such as failure to authenticate or redirect), or
    whatever the underlying connection classes raise.
    """
    # Allow connection reuse; prevent redirect loops.
    conn, connect_count = None, 32
    # Exceptions can occur anywhere.
    rdfile, wrfile = None, None
    # Construct headers.
    if headers is None: headers = {}
    headers.update({'Connection': 'Upgrade', 'Upgrade': 'websocket',
                    'Sec-WebSocket-Version': '13'})
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
                conn = httplib.HTTPConnection(purl.hostname, purl.port,
                                              **config)
                conn.response_class = TweakHTTPResponse
                conn.connect()
            elif purl.scheme == 'wss':
                conn = httplib.HTTPSConnection(purl.hostname, purl.port,
                                               **config)
                conn.response_class = TweakHTTPResponse
                conn.connect()
            else:
                raise ValueError('Bad URL scheme.')
            # Subprotocols.
            if isinstance(protos, str):
                headers['Sec-WebSocket-Protocol'] = protos
            elif protos is not None:
                headers['Sec-WebSocket-Protocol'] = ', '.join(protos)
            # Construct key.
            key = base64.b64encode(os.urandom(16)).decode('ascii')
            headers['Sec-WebSocket-Key'] = key
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
            except:
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
        # Verify key and other fields.
        if resp.getheader('Sec-WebSocket-Accept') != process_key(key):
            raise ProtocolError('Invalid reply key')
        if resp.getheader('Sec-WebSocket-Extensions'):
            raise ProtocolError('Extensions not supported')
        p = resp.getheader('Sec-WebSocket-Protocol')
        if p and (not protos or p not in protos):
            raise ProtocolError('Invalid subprotocol received')
        # Construct return value.
        # NOTE: Have to read from resp itself, as it might have buffered the
        #       beginning of the server's data, as those might have been
        #       coalesced with the headers.
        ret = wrap(resp, wrfile)
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
            except:
                pass
        raise
