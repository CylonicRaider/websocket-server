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
    from urllib.parse import quote, unquote, urlsplit, urlunsplit, parse_qsl
except ImportError:
    from urllib import quote, unquote
    from urlparse import urlsplit, urlunsplit, parse_qsl

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
    purl = urlsplit(url)
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
    def create(cls, name, value, url):
        """
        create(name, value, url) -> new instance

        Create a cookie with the given name and value, initializing
        attributes from the given URL. The host name from it is used
        for the Domain attribute, the path for the Path, query string
        parameters are converted into additional attributes.
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

        Convert the given cookie attribute to a programmatically usable
        format. key is the name of the attribute (and always present); value
        is either the value as a string, or None if no value was given. Both
        key and value have surrounding whitespace removed.
        The default implementation turns false values (including empty
        strings) into None and properly parses the Expires, Path, and Max-Age
        attributes.
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
            make_attrs = lambda: ()
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
            scnt = path.count('/')
            if scnt <= 1:
                path = '/'
            else:
                path = path[:path.rindex('/')]
            pmatch = lambda x: paths_match(path, x)
        self.filter(lambda c: not (dmatch(c.key[0]) and pmatch(c.key[1])))

    def cleanup(self, expired=True, session=True):
        """
        cleanup(expired=True, session=True) -> None

        Remove expired and/or session cookies from the jar. Note that
        expiring and being a session cookie are mutually exclusive.
        """
        def check(cookie):
            fresh = cookie.is_fresh()
            if expired and not fresh: return False
            if session and fresh is Ellipsis: return False
            return True
        self.filter(check)

    def query(self, url):
        """
        query(url) -> list

        Retrieve a list of cookies that would be delivered to url.
        Expired cookies are not returned, but not removed from the jar,
        either; use cleanup() for that.
        """
        info = parse_url(url)
        ret = list(filter(lambda c: c._matches(info) and c.is_fresh(), self))
        # We don't (reliably) record the creation time, so the path alone
        # will do.
        ret.sort(key=lambda c: c['Path'], reverse=True)
        return ret

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
        def make_attrs(cookie):
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
        def format_attr(key, value):
            if key.lower() == 'expires':
                return time.strftime('expires="%Y-%m-%d %H:%M:%S Z"',
                                     time.gmtime(value))
            else:
                return cookie._format_attr(key, value)
        stream.write('#LWP-Cookies-2.0\n')
        for cookie in self:
            stream.write('Set-Cookie3: %s\n' % cookie._format(make_attrs,
                                                              format_attr))
        stream.flush()

    def load_from(self, stream):
        """
        load_from(stream) -> None

        See FileCookieJar for details.
        """
        def parse_attr(key, value):
            key = self.ATTR_CASE.get(key, key)
            return Cookie._parse_attr(key, value)
        def make_url(url, attrs):
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
            self.add(Cookie.parse(m.group(1), parse_attr=parse_attr,
                                  make_url=make_url))
