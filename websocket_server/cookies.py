# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
Cookie management utilities.

(Mostly) compliant to RFC 6265. The alternatives present in the
standard library are, frankly, utterly insufficient.
"""

import re
import time
from . import tools
from .compat import bytes, unicode

try:
    from urllib.parse import quote, unquote, urlparse
except ImportError:
    from urllib import quote, unquote
    from urlparse import urlparse

__all__ = ['Cookie', 'CookieJar', 'FileCookieJar', 'CookieLoadError']

SECURE_SCHEMES = ['https', 'wss']
HTTP_SCHEMES = ['http', 'https', 'ws', 'wss']

def domains_match(base, probe):
    """
    domains_match(base, probe) -> bool

    Return whether probe should "match" base if both are interpreted
    as domain names. Implements RFC6265, Section 5.1.3.
    """
    if probe == base:
        return True
    elif not probe.endswith(base) or not probe[:-len(base)].endswith('.'):
        return False
    elif probe.replace('.', '').isdigit() or ':' in probe:
        # Crude heuristic to match IP addresses.
        return False
    else:
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
    parse_url(url) -> (str, str, str)

    Parse url and return the scheme, host, and path normalized as
    convenient for Cookie.match() et al.
    """
    purl = urlparse(url)
    return (purl.scheme.lower(), (purl.hostname or '').lower(),
            (purl.path or '/'))

class CookieLoadError(Exception):
    """
    Raised if trying to load cookies from a badly formatted file.
    """
    pass

class Cookie:
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

    Make sure to choose only appropriate names/values; Cookie does not
    empoly any means of automatic escaping.
    """

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
        URL from the URL as passed and the attribute dictionary (and
        also to modify the attributes in-place before they are passed
        into the Cookie constructor).
        """
        if parse_attr is None: parse_attr = cls._parse_attr
        if make_url is None: make_url = lambda u, a: u
        name, value, attrs = None, None, {}
        for n, token in enumerate(string.split(';')):
            k, s, v = token.partition('=')
            if not s: v = None
            if n == 0:
                name, value = k.strip(), v.strip()
            else:
                k, v = parse_attr(k.strip(), v.strip())
                attrs[k] = v
        url = make_url(url, attrs)
        return cls(name, value, url, **attrs)

    @classmethod
    def _parse_attr(cls, key, value):
        """
        _parse_attr(key, value) -> (key, value)

        Convert the given cookie attribute to a programmatically usable
        format. key is the name of the attribute (and always present); value
        is either the value as a string, or None if no value was given. Both
        key and value have surrounding whitespace removed.
        The default implementation turns false values (including empty
        strings) into None and properly parses the Expires, Path, and Max-Age
        attributes.
        """
        lkey = key.lower()
        if value.startswith('"') and value.endswith('"'):
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
        self._attrs = attrs
        self._keys = dict((k.lower(), k) for k in attrs.keys())
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
        return '<%s %s>' % (self.__class__.__name__, self.format())

    def __len__(self):
        """
        len(self) -> int

        Return the amount of cookie attributes in self.
        """
        return len(self._attrs)

    def __iter__(self):
        """
        iter(self) -> iter

        Return an iterator over the names of the cookie attributes in
        self.
        """
        return iter(self._attrs)

    def __contains__(self, key):
        """
        key in self -> bool

        Return whether a cookie attribute with the given name exists.
        """
        return key.lower() in self._keys

    def __getitem__(self, key):
        """
        self[key] -> value

        Retrieve the cookie attribute corresponding to key.
        """
        return self._attrs[self._keys[key.lower()]]

    def __setitem__(self, key, value):
        """
        self[key] = value

        Set the cookie attribute corresponding to key to value.
        """
        lkey = key.lower()
        try:
            self._attrs[self._keys[lkey]] = value
        except KeyError:
            self._keys[lkey] = key
            self._attrs[key] = value
        self._update(lkey)

    def __delitem__(self, key):
        """
        del self[key]

        Remove the given cookie attribute.
        """
        lkey = key.lower()
        del self._attrs[self._keys[lkey]]
        del self._keys[lkey]

    def keys(self):
        """
        keys() -> Keys

        Return the keys of this mapping (i.e. the cookie attribute
        names) as a sequence. Depending on the Python version, it is a
        list or a dynamic view object; be careful.
        """
        return self._attrs.keys()

    def get(self, attr, default=None):
        """
        get(key, default=None) -> object

        Try to get the value of the given key, or default to default
        (which, in turn, defaults to None).
        """
        try:
            return self[attr]
        except KeyError:
            return default

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
            if self.get('Domain'):
                self._domain = self['Domain'].lower().lstrip('.')
                self._domain_exact = False
            elif self.url is None:
                self._domain = None
                self._domain_exact = True
            else:
                domain = urlparse(self.url).hostname
                self._domain = purl.hostname
                self._domain_exact = True
        elif attr == 'path':
            if self.get('Path') and self['Path'].startswith('/'):
                self._path = self['Path']
            elif self.url is None:
                self._path = None
            else:
                path = urlparse(self.url).path
                scnt = path.count('/')
                if scnt <= 1:
                    path = '/'
                else:
                    path = path[:path.rindex('/')]
                self._path = path
        elif attr in ('expires', 'max-age'):
            if self.get('Max-Age'):
                self._expires = self._created + self['Max-Age']
            elif self.get('Expires'):
                self._expires = self['Expires']
            else:
                self._expires = None
        if attr in ('domain', 'path'):
            self.key = (self._domain, self._path, self.name)

    def format(self, attrs=True):
        """
        format(attrs=True) -> str

        Return a textual representation of the cookie suitable for use
        as an HTTP header value. If attrs is false, only the name and
        value are formatted (making the output suitable for a
        client-side Cookie: header); if it is true, attributes are
        included (rendering it suitable for a server-side Set-Cookie:).
        """
        make_attrs = None if attrs else lambda x: ()
        return self._format(make_attrs)

    def _format(self, make_attrs=None, format_attr=None):
        """
        _format(make_attrs=None, format_attr=None) -> str

        Finely-tunable backend for format(). make_attrs is a function
        mapping a single Cookie instance to an iterable of key-value
        pairs representing the attributes, format_attr is a function
        compatible with the _format_attr() method that serializes the
        individual attributes. make_attrs defaults to a function that
        shortcuts into the internal attribute storage to simulate
        dict(self).items(); format_attr defaults to _format_attr().
        """
        if make_attrs is None: make_attrs = lambda x: self._attrs.items()
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

    def _matches(self, info):
        """
        _matches(info) -> bool

        Test whether this cookie would be delivered to the location
        described by info, which is a (scheme, host, path) tuple as
        returned by parse_url().
        """
        if None in (self._domain, self._path): return False
        # Test scheme.
        if 'Secure' in self and info[0] not in SECURE_SCHEMES:
            return False
        elif 'HttpOnly' in self and info[0] not in HTTP_SCHEMES:
            return False
        # Test host.
        if self._domain_exact:
            if info[1] != self._domain: return False
        else:
            if not domains_match(self._domain, info[1]): return False
        # Test path.
        return paths_match(self._path, info[2])

    def matches(self, url):
        """
        matches(url) -> bool

        Test whether this cookie would be delivered to url.
        """
        return self._matches(parse_url(url))

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

class CookieJar:
    """
    CookieJar() -> new instance

    A cookie jar contains cookies. This class does indeed implement the
    storage, management, and retrieval of cookies, providing a
    dedicated interface for that.

    NOTE that modifying the name, path, or domain of a cookie stored
         in a CookieJar leads to erratic behavior.
    """

    def __init__(self):
        """
        __init__() -> None

        See the class docstring for details.
        """
        self.cookies = {}

    def __repr__(self):
        """
        repr(self) -> str

        Return a programmer-friendly string representation of self.
        """
        return '<%s%s>' % (self.__class__.__name__, list(self))

    def __len__(self):
        """
        len(self) -> int

        Return the amount of cookies stored in self.
        """
        return len(self.cookies)

    def __contains__(self, obj):
        """
        obj in self -> bool

        Return whether the given cookie is contained in self.
        """
        return obj in self.cookies

    def __iter__(self):
        """
        iter(self) -> iter

        Return an iterator over all cookies in self.
        """
        return iter(self.cookies.values())

    def add(self, cookie):
        """
        add(cookie) -> None

        Add the given cookie to self, possibly replacing another one.
        """
        self.cookies[cookie.key] = cookie

    def remove(self, cookie):
        """
        remove(cookie) -> bool

        Remove the given cookie (or an equivalent) one from self.
        Returns whether an equivalent cookie was actually present.
        """
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
            path = '/' if not path.startswith('/') else path.rstrip('/')
            pmatch = lambda x: paths_match(path, x)
        self.filter(lambda c: not (dmatch(c.key[0]) and pmatch(c.key[1])))

    def clear_expired(self):
        """
        clear_expired() -> None

        Remove all cookies that have expired.
        """
        self.filter(lambda c: c.is_fresh())

    def clear_session(self):
        """
        clear_session() -> None

        Remove all session-only cookies.
        """
        self.filter(lambda c: c.is_fresh() is not Ellipsis)

    def query(self, url):
        """
        query(url) -> iterable

        Retrieve an iterable (i.e. whatever the builtin filter()
        returns) of cookies that would be delivered to url.
        Expired cookies are not returned, but not removed from the jar,
        either; use clear_expired() and clear_session() for cleaning
        up.
        """
        info = parse_url(url)
        return filter(lambda c: c._matches(info) and c.is_fresh(), self)

class FileCookieJar(CookieJar):
    """
    FileCookieJar(file=None) -> new instance

    FileCookieJar is an abstract extension of CookieJar providing methods
    to save cookies to a file and to restore them from it.
    file is a file object, or a filename, or None. If it is an object,
    it is expected to be opened in text mode, and should have a read(),
    a write(), a flush(), a seek(), and a close() method. If None, the
    jar is attached to no file, and only the stream-based serialization
    methods can be used.
    The class does not define a particular serialization format; this
    is delegated to subclasses.
    """

    def __init__(self, file=None):
        """
        __init__(file=None) -> None

        See class docstring for details.
        """
        CookieJar.__init__(self)
        self._file = file
        if isinstance(file, (str, unicode)):
            # HACK: r+ will fail if the file does not exist.
            try:
                self.file = open(file, 'r+')
            except IOError:
                self.file = open(file, 'w+')
        else:
            self.file = file

    def save(self):
        """
        save() -> None

        Serialize the cookies into the configured file, replacing it.
        """
        self.file.seek(0)
        self.save_to(self.file)

    def save_to(self, stream):
        """
        save_to(stream) -> None

        Serialize the cookies into the given stream.
        """
        raise NotImplementedError

    def load(self):
        """
        load() -> None

        Read cookies from the file. Replaces the internal state.
        """
        self.file.seek(0)
        self.load_from(self.file)

    def load_from(self, stream):
        """
        load_from(stream) -> None

        Read cookies from the given stream, replacing internal state.
        """
        raise NotImplementedError

    def close(self):
        """
        close() -> None

        Close the underlying file.
        """
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

    def save_to(self, stream):
        """
        save_to(stream) -> None

        See FileCookieJar for details.
        """
        def format_attr(key, value):
            if key.lower() == 'expires':
                return time.strftime('expires="%Y-%m-%d %H:%M:%S Z"',
                                     time.gmtime(value))
            elif key.lower() == 'max-age':
                return None
            else:
                return cookie._format_attr(key, value)
        stream.write('#LWP-Cookies-2.0\n')
        for cookie in self:
            stream.write('Set-Cookie3: %s\n' % cookie.format(format_attr))
        stream.flush()

    def load_from(self, stream):
        """
        load_from(stream) -> None

        See FileCookieJar for details.
        """
        def parse_attr(key, value):
            key = self.ATTR_CASE.get(key, key)
            return Cookie._parse_attr(key, value)
        self.clear()
        firstline = True
        for line in stream:
            if not line: continue
            if firstline:
                if not re.match(r'^\s*#\s*LWP-Cookies-2.0\s*$', line):
                    raise CookieLoadError('Invalid file header.')
                firstline = False
                continue
            m = re.match(r'^\s*Set-Cookie3:\s*(.*)\s*$', line)
            if not m:
                raise CookieLoadError('Invalid cookie line.')
            self.add(Cookie.parse(m.group(1), parse_attr=parse_attr))
