# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
Cookie management utilities.

The ones present in the standard library are, frankly, utterly
insufficient.
"""

from . import tools

try:
    from urllib.parse import quote
except ImportError:
    from urllib import quote

__all__ = ['Cookie']

class Cookie(dict):
    """
    Cookie(name, value, **attributes) -> new instance

    A single HTTP cookie. name and value are, respectively, the name
    and value of the cookie; attributes are additional key-value pairs
    containing meta-information about the cookie. The attributes can
    be accessed and modified using standard dict operations.

    Make sure to choose only appropriate names/values; Cookie does not
    empoly any means of automatic escaping.
    """

    def __init__(self, name, value, **attrs):
        """
        __init__(name, value, **attrs) -> None

        See class docstring for details.
        """
        dict.__init__(self, **attrs)
        self.name = name
        self.value = value

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
        if value is None:
            return key
        elif key == 'Expires':
            return '%s=%s' % (key, tools.format_rfc2616_date(value))
        elif key == 'Path':
            return '%s=%s' % (key, quote(value))
        else:
            return '%s=%s' % (key, value)
