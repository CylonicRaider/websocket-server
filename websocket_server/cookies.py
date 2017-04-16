# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
Cookie management utilities.

(Mostly) compliant to RFC 6265. The alternatives present in the
standard library are, frankly, utterly insufficient.
"""

import time
from . import tools

try:
    from urllib.parse import quote, unquote, urlparse
except ImportError:
    from urllib import quote, unquote
    from urlparse import urlparse

__all__ = ['Cookie']

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
    return (purl.scheme.lower(), (purl.hostname or '').lower(), purl.path)

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
    def parse(cls, string, url=None):
        """
        parse(string, url=None) -> new instance

        Parse the given textual cookie definition and return the
        equivalent object. url is the URL this cookie was received
        from.
        """
        name, value, attrs = None, None, {}
        for n, token in enumerate(string.split(';')):
            k, s, v = token.partition('=')
            if not s: v = None
            if n == 0:
                name, value = k, v
            else:
                k, v = cls._parse_attr(k, v)
                attrs[k] = v
        return cls(name, value, **attrs)

    @classmethod
    def _parse_attr(cls, key, value):
        """
        _parse_attr(key, value) -> (key, value)

        Convert the given cookie attribute to an programmatically usable
        format. key is the name of the attribute (and always present); value
        is either the value as a string, or None if no value was given. Both
        key and value have surrounding whitespace removed.
        The default implementation turns false values (including empty
        strings) into None and properly parses the Expires, Path, and Max-Age
        attributes.
        """
        lkey = key.lower()
        if not value:
            return (key, None)
        elif lkey == 'expires':
            return (key, tools.parse_rfc2616_date(value))
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

    def __delitem__(self, key, value):
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
        ret = [self.name, '=', self.value]
        if attrs:
            for k, v in self.items():
                s = self._format_attr(k, v)
                if s: ret.extend((';', s))
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
            return '%s=%s' % (key, tools.format_rfc2616_date(value))
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
        self.cookies = dict((k, v) for k, v in self.cookies.items()
                            if dmatch(k[0]) and pmatch(k[1]))
