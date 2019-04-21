# websocket_server -- WebSocket/HTTP server/client library
# https://github.com/CylonicRaider/websocket-server

"""
Cookie management utilities.

(Mostly) compliant to RFC 6265. The alternatives present in the Python
standard library are too tightly coupled to be used outside it.

Most classes in this module are *not* thread-safe; exceptions are noted
explicitly.
"""

import os, re, time
import threading

from . import tools
from .compat import unicode

try: # Py2K
    from urllib import quote, unquote
    from urlparse import urlsplit, urlunsplit, parse_qsl
except ImportError: # Py3K
    from urllib.parse import quote, unquote, urlsplit, urlunsplit, parse_qsl

__all__ = ['Cookie', 'CookieJar', 'FileCookieJar', 'LWPCookieJar',
           'CookieLoadError', 'parse_cookie', 'format_set_cookie']

SECURE_SCHEMES = ['https', 'wss']
HTTP_SCHEMES = ['http', 'https', 'ws', 'wss']

COOKIE_HEADER = re.compile(r'(?i)Cookie\s*:\s+')

def domains_match(base, probe):
    """
    domains_match(base, probe) -> bool

    Return whether probe should "match" base if both are interpreted
    as domain names. Implements RFC6265, Section 5.1.3.
    """
    if probe == base:
        # Equal domains always match.
        return True
    prefix = probe[:-len(base)]
    if not probe.endswith(base) or (prefix and not prefix.endswith('.')):
        # probe must be a suffix of base, and be separated by a dot.
        return False
    elif probe.replace('.', '').isdigit() or ':' in probe:
        # probe must not be an IP address; applying a crude heuristic.
        return False
    else:
        # If the above two ("negative") conditions do not match, this case
        # is invoked.
        return True

def paths_match(base, probe):
    """
    paths_match(base, probe) -> bool

    Return whether probe is considered to "match" base if both are
    interpreted as path names. Implements RFC6265, Section 5.1.4.
    """
    return (probe == base or probe.startswith(base) and
            (base.endswith('/') or probe[len(base):].startswith('/')))

def parse_url(url):
    """
    parse_url(url) -> (scheme, host, path)

    Parse url and return the scheme, host, and path as strings normalized as
    convenient for Cookie.matches() et al.
    """
    purl = urlsplit(url)
    return (purl.scheme.lower(), (purl.hostname or '').lower(),
            (purl.path or '/'))

def parse_cookie(string):
    """
    parse_cookie(string) -> dict

    Parse the given Cookie: header value and return a mapping from cookie
    names to values.
    """
    ret = {}
    for el in string.split(';'):
        n, _, v = el.partition('=')
        ret[n.strip()] = v.strip()
    return ret

def format_set_cookie(cookie):
    """
    format_set_cookie(cookie) -> str

    Format the given cookie suitable for a Set-Cookie: header value.
    A convenience wrapper around cookie.format('set') included for
    symmetry to parse_cookie().
    """
    return cookie.format('set')

class CookieLoadError(Exception):
    """
    Raised if trying to load cookies from an incorrectly formatted file.
    """

class Cookie(object):
    """
    Cookie(name, value, url=None, **attributes) -> new instance

    A single HTTP cookie. name and value are, respectively, the name
    and value of the cookie. url is the URL the cookie references, or
    None; if present, it is used to derive default values for certain
    attributes (as demanded by the RFC). attributes are additional
    key-value pairs containing meta-information about the cookie.
    Cookie implements a bare-bones mapping interface (enough to pass
    the dict constructor and collections.MutableMapping); use that to
    access/modify cookie attributes. Lookup and modification is
    case-insensitive; iteration preserves the case at the time of
    insertion (delete and re-add an attribute to force a specific
    case).

    WARNING: Make sure to choose only appropriate names/values; Cookie
             does not empoly any means of automatic escaping.

    Instance members are:
    name   : The name of the cookie.
    value  : The value of the cookie.
    url    : The URL the cookie is associated with.
    key    : A sorting and comparison key. Read-only.
    attrs  : The attributes of the cookie.
    relaxed: Whether certain security features (i.e. the Secure and
             HttpOnly cookie attributes) should be ignored. Use with
             caution.
    """

    @classmethod
    def create(cls, name, value, url):
        """
        create(name, value, url) -> new instance

        Create a cookie with the given name and value, initializing
        attributes from the given URL. The scheme is used to set the
        Secure attribute (or not), the host name from it is used for
        Domain, the path for Path, and query string parameters are
        converted into additional attributes.
        """
        purl = urlsplit(url)
        attrs = tools.CaseDict()
        if purl.scheme in SECURE_SCHEMES: attrs['Secure'] = None
        if purl.hostname: attrs['Domain'] = purl.hostname
        attrs['Path'] = purl.path or '/'
        for k, v in parse_qsl(purl.query, True):
            if v:
                attrs[k] = v
            else:
                attrs[k] = None
        return cls(name, value, url, **attrs)

    @classmethod
    def parse(cls, string, url=None, parse_attr=None, make_url=None):
        """
        parse(string, url=None, parse_attr=None, make_url=None)
            -> new instance

        Parse the given textual cookie definition and return the
        equivalent object. url is the URL this cookie was received
        from.
        parse_attr can be used to dependency-inject a custom attribute
        parser; the _parse_attr method of the same class is used as
        a default. make_url can similarly be used to construct a cookie
        URL from the URL as passed and the attribute CaseDict (and
        also to modify the attributes in-place before they are passed
        into the Cookie constructor).
        """
        if parse_attr is None: parse_attr = cls._parse_attr
        if make_url is None: make_url = lambda u, a: u
        name, value, attrs = None, None, tools.CaseDict()
        for n, token in enumerate(string.split(';')):
            k, s, v = token.partition('=')
            if not s: v = None
            if n == 0:
                name, value = k.strip(), (v if v is None else v.strip())
            else:
                k, v = parse_attr(k.strip(), v if v is None else v.strip())
                attrs[k] = v
        url = make_url(url, attrs)
        return cls(name, value, url, **attrs)

    @classmethod
    def _parse_attr(cls, key, value):
        """
        _parse_attr(key, value) -> (key, value)

        Convert the given cookie attribute to a programmatically
        usable format. key is the name of the attribute (and always
        present); value is either the value as a string, or None if no
        value was given. Both key and value have surrounding whitespace
        removed. The default implementation turns false values
        (including empty strings) into None and properly parses the
        Expires, Path, and Max-Age attributes.
        """
        lkey = key.lower()
        if value and value.startswith('"') and value.endswith('"'):
            value = value[1:-1].replace('\\"', '"').replace('\\\\', '\\')
        if not value:
            return (key, None)
        elif lkey == 'expires':
            return (key, tools.parse_http_date(value))
        elif lkey == 'path':
            return (key, unquote(value))
        elif lkey == 'max-age':
            return (key, int(value))
        else:
            return (key, value)

    def __init__(self, name, value, url=None, **attrs):
        """
        __init__(name, value, url=None, **attrs) -> None

        See class docstring for details.
        """
        self.name = name
        self.value = value
        self.url = url
        self.key = None
        self.attrs = tools.CaseDict(attrs)
        self.relaxed = False
        self._domain = None
        self._domain_exact = False
        self._path = None
        self._expires = None
        self._created = time.time()
        self._update(None)

    def __repr__(self):
        """
        repr(self) -> str

        Return a programmer-friendly string representation of self.
        """
        return '<%s %s%s>' % (self.__class__.__name__, self.format(),
            '; _url=' + self.url if self.url else '')

    def __len__(self):
        """
        len(self) -> int

        Return the amount of cookie attributes in self.
        """
        return len(self.attrs)

    def __iter__(self):
        """
        iter(self) -> iter

        Return an iterator over the names of the cookie attributes in
        self.
        """
        return iter(self.attrs)

    def __contains__(self, key):
        """
        key in self -> bool

        Return whether a cookie attribute with the given name exists.
        """
        return (key in self.attrs)

    def __getitem__(self, key):
        """
        self[key] -> value

        Retrieve the cookie attribute corresponding to key.
        """
        return self.attrs[key]

    def __setitem__(self, key, value):
        """
        self[key] = value

        Set the cookie attribute corresponding to key to value.
        """
        self.attrs[key] = value
        self._update(key.lower())

    def __delitem__(self, key):
        """
        del self[key]

        Remove the given cookie attribute.
        """
        del self.attrs[key]

    def keys(self):
        """
        keys() -> Keys

        Return the keys of this mapping (i.e. the cookie attribute
        names) as a sequence. Depending on the Python version, it is a
        list or a dynamic view object; be careful.
        """
        return self.attrs.keys()

    def _update(self, attr):
        """
        _update(attr) -> None

        Update the internal state of the cookie. attr gives a hint at
        which parts of the state to refresh; if None, everything is
        renewed.
        """
        if attr is None:
            self._update('Domain')
            self._update('Path')
            self._update('Expires')
            return
        attr = attr.lower()
        if attr == 'domain':
            value = self.attrs.get('Domain')
            if value:
                self._domain = value.lower().lstrip('.')
                self._domain_exact = False
            elif self.url is None:
                self._domain = None
                self._domain_exact = True
            else:
                domain = urlsplit(self.url).hostname
                self._domain = domain
                self._domain_exact = True
        elif attr == 'path':
            value = self.attrs.get('Path')
            if value and value.startswith('/'):
                self._path = value
            elif self.url is None:
                self._path = None
            else:
                path = urlsplit(self.url).path
                scnt = path.count('/')
                if scnt <= 1:
                    path = '/'
                else:
                    path = path[:path.rindex('/')]
                self._path = path
        elif attr in ('expires', 'max-age'):
            if self.attrs.get('Max-Age'):
                self._expires = self._created + self['Max-Age']
            elif self.attrs.get('Expires'):
                self._expires = self['Expires']
            else:
                self._expires = None
        if attr in ('domain', 'path'):
            self.key = (self._domain, self._path, self.name)

    def format(self, mode='all'):
        """
        format(mode='all') -> str

        Return a textual representation of the cookie, suitable for
        inclusion into a HTTP header, with details depending on mode:
        'all'   : All cookie attributes are included.
        'set'   : Attributes including underscores (meant for internal
                  client-side use) are omitted; can be included in a
                  Set-Cookie: header.
        'return': No attributes are included at all; result can be
                  included in a Cookie: header.
        """
        if mode == 'all':
            make_attrs = None
        elif mode == 'set':
            make_attrs = lambda x: ((k, v) for k, v in self.attrs.items()
                                    if '_' not in k)
        elif mode == 'return':
            make_attrs = lambda x: ()
        else:
            raise ValueError('Bad cookie formatting mode.')
        return self._format(make_attrs)

    def _format(self, make_attrs=None, format_attr=None):
        """
        _format(make_attrs=None, format_attr=None) -> str

        Finely-tunable backend for format(). make_attrs is a function
        mapping a single Cookie instance to an iterable of key-value
        pairs representing the attributes, format_attr is a function
        compatible with the _format_attr() method that serializes the
        individual attributes. make_attrs defaults to a function that
        returns self.attrs.items(); format_attr defaults to
        _format_attr().
        """
        if make_attrs is None: make_attrs = lambda x: self.attrs.items()
        if format_attr is None: format_attr = self._format_attr
        ret = [self.name, '=', self.value]
        for k, v in make_attrs(self):
            s = format_attr(k, v)
            if s: ret.extend(('; ', s))
        return ''.join(ret)

    def _format_attr(self, key, value):
        """
        _format_attr(key, value) -> str

        Return a proper textual representation of the given attribute.
        To suppress displaying the attribute altogether, return a false
        value (such as the empty string or None).
        The default implementation returns a bare name if value is
        None, and properly formats the Expires and Path attributes.
        """
        lkey = key.lower()
        if value is None:
            return key
        elif lkey == 'expires':
            return '%s=%s' % (key, tools.format_http_date(value))
        elif lkey == 'path':
            return '%s=%s' % (key, quote(value))
        else:
            return '%s=%s' % (key, value)

    def _matches(self, info, path=True):
        """
        _matches(info, path=True) -> bool

        Test whether this cookie would be delivered to the location
        described by info, which is a (scheme, host, path) tuple as
        returned by parse_url().
        If path is false, the path is assumed to always match (as
        needed for valid()).
        """
        if None in (self._domain, self._path): return False
        # Test scheme.
        if not self.relaxed:
            if 'Secure' in self and info[0] not in SECURE_SCHEMES:
                return False
            elif 'HttpOnly' in self and info[0] not in HTTP_SCHEMES:
                return False
        # Test domain.
        if self._domain_exact:
            if info[1] != self._domain: return False
        else:
            if not domains_match(self._domain, info[1]): return False
        # Test path.
        if not path: return True
        return paths_match(self._path, info[2])

    def matches(self, url):
        """
        matches(url) -> bool

        Test whether this cookie would be delivered to url.
        """
        return self._matches(parse_url(url))

    def valid(self):
        """
        valid() -> bool

        Check the attributes of the cookie for consistency with its URL
        (if any).
        """
        return (not self.url or self._matches(parse_url(self.url), False))

    def is_fresh(self):
        """
        is_fresh() -> bool or Ellipsis

        Return whether this cookie has *not* expired.
        If the cookie has a expiration date or a maximum age, this
        returns a bool; otherwise (i.e. for session cookies), Ellipsis
        (which is true) is returned.
        """
        if self._expires is None: return Ellipsis
        return (time.time() < self._expires)

class CookieJar(object):
    """
    CookieJar() -> new instance

    A cookie jar contains cookies. This class does indeed implement the
    storage, management, and retrieval of cookies, providing a
    dedicated interface for that.

    Instance attributes are:
    cookies: The underlying mapping of cookies. Prefer the methods of
             this class to manipulating this directly.
    relaxed: Whether certain security features should be ignored. The
             value of this attribute is passed on to Cookie instances
             created by this class. Use with caution.

    CookieJar implements the context manager procotol, asserting an
    internal (reentrant) threading lock while "entered". While the
    individual CookieJar methods are thread-safe (as well), the
    enclosed Cookie instances are *not* -- in order to perform multiple
    coordinated accesses (including retrieving and mutating a cookie),
    synchronize the entire sequence of accesses using a with block.

    NOTE that modifying the name, path, or domain of a cookie stored
         in a CookieJar leads to erratic behavior.
    """

    def __init__(self):
        """
        __init__() -> None

        See the class docstring for details.
        """
        self.cookies = {}
        self.relaxed = False
        self.lock = threading.RLock()

    def __enter__(self):
        "Context manager entry; see class docstring for details."
        return self.lock.__enter__()
    def __exit__(self, *args):
        "Context manager exit; see class docstring for details."
        self.lock.__exit__(*args)

    def __repr__(self):
        """
        repr(self) -> str

        Return a programmer-friendly string representation of self.
        """
        with self:
            return '<%s%s>' % (self.__class__.__name__, list(self))

    def __len__(self):
        """
        len(self) -> int

        Return the amount of cookies stored in self.
        """
        with self:
            return len(self.cookies)

    def __contains__(self, obj):
        """
        obj in self -> bool

        Return whether the given cookie is contained in self.
        """
        with self:
            return obj in self.cookies

    def __iter__(self):
        """
        iter(self) -> iter

        Return an iterator over all cookies in self.
        """
        with self:
            return iter(self.cookies.values())

    def add(self, cookie, validate=False):
        """
        add(cookie, validate=False) -> bool

        Add the given cookie to self, possibly replacing another one.
        If validate is true, the cookie is validated, i.e., the
        addition is rejected unless the cookie's valid() method returns
        True, and the cookie does not originate from a "non-HTTP" API
        or there exists no former cookie with the HttpOnly attribute
        set (RFC 6265, Section 5.3).
        The "origination from a non-HTTP API" is determined by
        inspecting the url attribute of the cookie; use the
        Cookie.create() class method to craft a cookie that passes the
        validation.
        """
        with self:
            if self.relaxed: cookie.relaxed = True
            if validate:
                if not cookie.valid(): return False
                try:
                    old = self.cookies[cookie.key]
                    # Force a KeyError unless the attribute is present.
                    old['HttpOnly'] #pylint: disable=W0104
                except KeyError:
                    pass
                else:
                    if cookie.url is None: return False
                    purl = urlsplit(cookie.url)
                    if purl.scheme not in HTTP_SCHEMES: return False
            self.cookies[cookie.key] = cookie
            return True

    def remove(self, cookie):
        """
        remove(cookie) -> bool

        Remove the given cookie (or an equivalent one) from self.
        Returns whether an equivalent cookie was actually present.
        """
        with self:
            try:
                del self.cookies[cookie.key]
                return True
            except KeyError:
                return False

    def filter(self, predicate=None):
        """
        filter(predicate=None) -> None

        Apply predicate to all cookies in the jar and remove those for
        which it did not return something true.
        If predicate is None, every cookie satisfies it.
        Since this function recreates the internal cookie store from
        the keys stored in cookies, it can be used to regain integrity
        after modifying the domain, path, or name attributes of
        cookies.
        """
        with self:
            self.cookies = dict((c.key, c) for c in filter(predicate, self))

    def clear(self, domain=None, path=None):
        """
        clear(domain=None, path=None) -> None

        Evict some or all cookies from the jar.
        If domain is not None, only cookies with the given domain are
        removed; analogously, only cookies matching path are removed
        if it is given.

        NOTE that the matching relation is reversed in comparison to
             querying, i.e., evicting cookies for "example.com" will
             also remove such for "test.example.com".
             domain and path are normalized similarly to how the Cookie
             implementation does.
        """
        with self:
            if domain is None and path is None:
                self.cookies.clear()
                return
            if domain is None:
                dmatch = lambda x: False
            else:
                domain = domain.lower().lstrip('.')
                dmatch = lambda x: domains_match(domain, x)
            if path is None:
                pmatch = lambda x: False
            else:
                scnt = path.count('/')
                if scnt <= 1:
                    path = '/'
                else:
                    path = path[:path.rindex('/')]
                pmatch = lambda x: paths_match(path, x)
            self.filter(lambda c: not (dmatch(c.key[0]) and pmatch(c.key[1])))

    def cleanup(self, expired=True, session=False):
        """
        cleanup(expired=True, session=False) -> None

        Remove expired and/or session cookies from the jar. Note that
        expiring and being a session cookie are mutually exclusive.
        """
        def check(cookie):
            "Determine whether the given cookie should *not* be evicted."
            fresh = cookie.is_fresh()
            if expired and not fresh: return False
            if session and fresh is Ellipsis: return False
            return True
        with self:
            self.filter(check)

    def query(self, url):
        """
        query(url) -> list

        Retrieve a list of cookies that would be delivered to url.
        Expired cookies are not returned, but not removed from the jar,
        either; use cleanup() for that.
        """
        info = parse_url(url)
        with self:
            ret = [c for c in self if c._matches(info) and c.is_fresh()]
            # We don't (reliably) record the creation time, so the path alone
            # will do.
            ret.sort(key=lambda c: c['Path'], reverse=True)
            return ret

    def format_cookie(self, url):
        """
        format_cookie(url) -> str or None

        Format a ready-to-use Cookie: header value for sending in a
        request to url, or None if there are no cookies for it.
        """
        with self:
            cookies = self.query(url)
            if not cookies: return None
            return '; '.join(c.format('return') for c in cookies)

    def process_set_cookie(self, url, string):
        """
        process_set_cookie(url, string) -> None

        Parse the given Set-Cookie: header value and update the cookie
        jar as necessary.
        url is the URL the response to whose request the cookie was
        received from; string is the actual Set-Cookie header value.
        """
        self.add(Cookie.parse(string, url), True)

class FileCookieJar(CookieJar):
    """
    FileCookieJar(file=None, mode=None) -> new instance

    FileCookieJar is an abstract extension of CookieJar providing
    methods to save cookies to a file and to restore them from it.
    file is a file object, or a filename, or None. If it is an object,
    it is expected to be opened in text mode, and should have a read(),
    a write(), a flush(), a seek(), and a close() method. If None, the
    jar is attached to no file, and only the stream-based serialization
    methods can be used.
    If mode is not None, it is a numerical file mode as used by
    os.chmod(), and the cookie file's access mode is changed to it
    after creating it (*not* when an already-existing file is opened).
    The class does not define a particular serialization format; this
    is delegated to subclasses.

    Instance attributes (aside from interited ones) are:
    file: The file object underlying this instance.
    """

    def __init__(self, file=None, mode=None):
        """
        __init__(file=None, mode=None) -> None

        See class docstring for details.
        """
        CookieJar.__init__(self)
        self._file = file
        self._mode = mode
        if isinstance(file, (str, unicode)):
            # HACK: r+ will fail if the file does not exist.
            try:
                self.file = open(file, 'r+')
            except IOError:
                self.file = open(file, 'w+')
                # HACK: fchmod() is less racy, and less widely available.
                try:
                    os.fchmod(self.file.fileno(), mode)
                except NameError:
                    os.chmod(file, mode)
        else:
            self.file = file

    def save(self, cleanup=True):
        """
        save(cleanup=True) -> None

        Serialize the cookies into the configured file, replacing its
        contents. If cleanup is true, expired or session-only cookies
        are omitted, otherwise not.
        """
        def check(cookie):
            f = cookie.is_fresh()
            return (f and f is not Ellipsis)
        with self:
            self.file.seek(0)
            self.save_to(self.file, (check if cleanup else None))
            self.file.truncate()

    def save_to(self, stream, predicate=None):
        """
        save_to(stream, predicate=None) -> None

        Serialize the cookies matching predicate (all if it is None)
        into the given stream.
        """
        with self:
            self._save_to(stream, predicate)

    def _save_to(self, stream, predicate=None):
        """
        _save_to(stream, predicate=None) -> None

        Back-end method for save_to(), which calls this method with the
        synchronization lock held.
        The default "implementation" raises a NotImplementedError.
        """
        raise NotImplementedError

    def load(self, replace=False):
        """
        load(replace=False) -> None

        Read cookies from the file. If replace is true, the cookies
        from the file replace the internally stored ones, otherwise,
        they are merged, with the cookies from the file taking
        precedence.
        """
        with self:
            self.file.seek(0)
            if replace: self.clear()
            self.load_from(self.file)

    def load_from(self, stream):
        """
        load_from(stream) -> None

        Read cookies from the given stream, merging with the internal
        state (cookies from the stream take precedence).
        """
        with self:
            self._load_from(stream)

    def _load_from(self, stream):
        """
        _load_from(stream) -> None

        Back-end method for load_from(), which calls this method with the
        synchronization lock held.
        The default "implementation" raises a NotImplementedError.
        """
        raise NotImplementedError

    def close(self):
        """
        close() -> None

        Close the underlying file.
        """
        with self:
            self.file.close()

class LWPCookieJar(FileCookieJar):
    """
    LWPCookieJar(filename=None) -> new instance

    This class extends FileCookieJar with concrete (de)serialization
    methods aiming to be compatible to the same-named class from the
    standard library.
    """

    # Canonicalize attribute case.
    ATTR_CASE = {'secure': 'Secure', 'discard': 'Discard',
        'version': 'Version', 'port': 'Port', 'path': 'Path',
        'domain': 'Domain', 'expires': 'Expires', 'comment': 'Comment',
        'commenturl': 'CommentURL'}

    def _save_to(self, stream, predicate=None):
        """
        _save_to(stream, predicate=None) -> None

        See FileCookieJar for details.
        """
        def make_attrs(cookie):
            "Prepare the attribute set of cookie for export."
            ret = tools.CaseDict(cookie)
            if cookie._domain_exact:
                ret.pop('domain_dot', None)
            else:
                ret['domain_dot'] = None
            if 'path' in ret:
                ret['path_spec'] = None
            else:
                ret.pop('path_spec', None)
            ret['Domain'] = cookie._domain
            ret['Path'] = cookie._path
            ret.pop('Max-Age', None)
            ret['Expires'] = cookie._expires
            return ret.items()
        def format_attr(cookie, key, value):
            "Format an individual cookie attribute."
            if key.lower() == 'expires':
                return time.strftime('expires="%Y-%m-%d %H:%M:%S Z"',
                                     time.gmtime(value))
            else:
                return cookie._format_attr(key, value)
        stream.write('#LWP-Cookies-2.0\n')
        for cookie in filter(predicate, self):
            stream.write('Set-Cookie3: %s\n' % cookie._format(make_attrs,
                lambda k, v: format_attr(cookie, k, v)))
        stream.flush()

    def _load_from(self, stream):
        """
        _load_from(stream) -> None

        See FileCookieJar for details.
        """
        def parse_attr(key, value):
            "Restore the canonical case of attribute keys."
            key = self.ATTR_CASE.get(key, key)
            return Cookie._parse_attr(key, value)
        def make_url(url, attrs):
            "Undo the attribute and URL modifications done when saving."
            # Assemble URL.
            parts = ['https' if 'Secure' in attrs else 'http',
                     attrs['Domain'], attrs['Path'], '', '']
            if 'Port' in attrs: parts[1] += ':%s' % attrs['Port']
            # Restore the Domain and Path attributes.
            if 'domain_dot' not in attrs:
                del attrs['Domain']
            else:
                attrs.pop('domain_dot', None)
            if 'path_spec' not in attrs:
                del attrs['Path']
            else:
                attrs.pop('path_spec', None)
            return urlunsplit(parts)
        firstline = True
        for line in stream:
            if not line: continue
            if firstline:
                if not re.match(r'^\s*#\s*LWP-Cookies-2.0\s*$', line):
                    raise CookieLoadError('Invalid file header.')
                firstline = False
                continue
            if re.match(r'^\s*#', line):
                continue
            m = re.match(r'^\s*Set-Cookie3:\s*(.*)\s*$', line)
            if not m:
                raise CookieLoadError('Invalid cookie line.')
            self.add(Cookie.parse(m.group(1), parse_attr=parse_attr,
                                  make_url=make_url))

class RequestHandlerCookies(object):
    """
    RequestHandlerCookies(handler, descs) -> new instance

    This class automates the gathering and sending of cookie headers in
    BaseHTTPRequestHandler instances. handler is the request handler object
    to work with. descs is a mapping of "cookie descriptions" that are used to
    reconstruct attributes of cookies received from the client; descs maps
    cookie names to URL-s which are used as third parameters to
    Cookie.create() (see there for details). descs also acts as a whitelist;
    cookies not included in it are ignored and (in particular) not sent back.
    If descs contains a mapping for the None singleton, however, all cookies
    are allowed, and the description corresponding to None is used as a
    default.

    The mapping protocol is partially implemented; for complex operations,
    create a dict instance. Assigning cookies whose name does not match the
    key they are mapped to is possible, but of little use (and may be
    forbidden in the future).

    Normally, you do not need to create instances of this class; the
    HTTPRequestHandler class does so automatically.

    The "handler" and "descs" attributes hold the values of the corresponding
    constructor arguments.
    """

    def __init__(self, handler, descs):
        """
        __init__(handler, descs) -> None

        See class docstring for details.
        """
        self.handler = handler
        self.descs = descs
        self.cookies = {}

    def __contains__(self, key):
        """
        key in self -> bool

        Return whether this instance contains a cookie with the given name.
        """
        return key in self.cookies

    def __getitem__(self, key):
        """
        self[key] -> value

        Return the cookie with the name key.
        """
        return self.cookies[key]

    def __setitem__(self, key, value):
        """
        self[key] = value

        Set the cookie corresponding to key to value.
        """
        self.cookies[key] = value

    def __delitem__(self, key):
        """
        del self[key]

        Remove the cookie named by key from self.
        """
        del self.cookies[key]

    def keys(self):
        """
        keys() -> Keys

        Return the names of the cookies stored by this instance.
        """
        return self.cookies.keys()

    def get(self, name, default=None):
        """
        get(name, default=None) -> value

        Return the cookie corresponding to name, or default if not found.
        """
        return self.cookies.get(name, default)

    def get_value(self, name, default=None):
        """
        get_value(name, default=None) -> value

        Retrieve the value of the cookie with the given name, or default if
        there is no such cookie.
        NOTE that cookies that were specified without a value (i.e. with a
             name only) have a value of None; it is not possible to
             differentiate them from their absence if a default of None is
             used.
        """
        c = self.get(name)
        return default if c is None else c.value

    def add(self, cookie):
        """
        add(cookie) -> Cookie

        Incorporate the given Cookie into this instance and return it.
        """
        self.cookies[cookie.name] = cookie
        return cookie

    def make(self, name, value, desc=None):
        """
        make(name, value, desc=None) -> Cookie

        Create and store a cookie with the given name and value, and return
        it. desc is used to initialize the cookie's attributes; if it is None,
        name must be in the descs instance member (or descs must have a None
        entry) and the corresponding entry is used as desc; if both desc is
        None and no stored description matching name exists, a KeyError is
        raised.
        """
        if desc is None:
            try:
                desc = self.descs[name]
            except KeyError:
                try:
                    desc = self.descs[None]
                except KeyError:
                    raise KeyError('Could not find description for '
                        'cookie %s' % name)
        return self.add(Cookie.create(name, value, desc))

    def load(self):
        """
        load() -> None

        Update the internal cookie mapping with cookies extracted from the
        handler's HTTP request. Cookies whose names are not in the descs
        member are ignored.
        """
        try: # Py3K
            values = self.handler.headers.get_all('Cookie', ())
        except AttributeError: # Py2K
            hdrlines = self.handler.headers.getallmatchingheaders('Cookie')
            # Assemble folded lines. ._.
            headers = []
            for line in hdrlines:
                if line[:1].isspace():
                    # A continuation line in the very beginning should not
                    # happen.
                    headers[-1] += line
                else:
                    headers.append(line)
            values = [COOKIE_HEADER.sub('', h) for h in headers]
        pairs = {}
        for v in values:
            pairs.update(parse_cookie(v))
        for k, v in pairs.items():
            try:
                self.make(k, v)
            except KeyError:
                pass

    def send(self):
        """
        send() -> None

        Submit the cookies stored in this instance to the HTTP client.
        """
        for c in self.cookies.values():
            self.handler.send_header('Set-Cookie', c.format('set'))

    def gc(self):
        """
        gc() -> None

        Remove all cookies from this instance that are not "fresh" (as
        determined by their is_fresh() method).
        """
        for k, cookie in tuple(self.cookies.items()):
            if not cookie.is_fresh():
                del self.cookies[k]
