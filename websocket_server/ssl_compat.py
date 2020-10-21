# websocket_server -- WebSocket/HTTP server/client library
# https://github.com/CylonicRaider/websocket-server

"""
Common SSL support code.

This module papers over differences across various Py2K/Py3K versions.
"""

# pylint: disable=no-member

import ssl as _ssl

if hasattr(_ssl, 'create_default_context'): # Modern Py2K, Py3K
    HAS_REAL_CONTEXT = True

    def create_ssl_context(client_side, cert=None, key=None, ca=None):
        """
        Create an SSL context using the given configuration.

        cert is a file to read a client certificate from; key is a file
        containing a private key corresponding to the certificate (if omitted,
        the key must be located in the certificate file); ca is a file
        containing trusted CA certificates (if this is given, the other side
        must authenticate itself).

        This implementation uses the secure-by-default
        _ssl.create_default_context().
        """
        if client_side:
            purpose = _ssl.Purpose.SERVER_AUTH
        else:
            purpose = _ssl.Purpose.CLIENT_AUTH
        context = _ssl.create_default_context(purpose, cafile=ca)
        if cert is not None:
            context.load_cert_chain(cert, key)
        if ca is not None:
            context.verify_mode = _ssl.CERT_REQUIRED
        return context

elif hasattr(_ssl, 'SSLContext'): # Old Py2K, Py3K
    HAS_REAL_CONTEXT = True

    def create_ssl_context(client_side, cert=None, key=None, ca=None):
        """
        Create an SSL context using the given configuration.

        cert is a file to read a client certificate from; key is a file
        containing a private key corresponding to the certificate (if omitted,
        the key must be located in the certificate file); ca is a file
        containing trusted CA certificates (if this is given, the other side
        must authenticate itself).

        This implementation uses the SSLContext API directly (for older Python
        versions).
        """
        context = _ssl.SSLContext()
        if cert is not None:
            context.load_cert_chain(cert, key)
        if ca is not None:
            context.load_verify_locations(ca)
            context.verify_mode = _ssl.CERT_REQUIRED
        return context

else: # Ancient Py2K, Py3K
    HAS_REAL_CONTEXT = False

    class SSLContextShim(object):
        """
        A compatibility class for Python versions that have no SSLContext.

        This only implements the wrap_socket() method, and instances are
        created via this module's create_ssl_context().
        """

        def __init__(self, params):
            "Instance initializer; see the class docstring for details."
            self.params = params

        def wrap_socket(self, sock, server_side=False):
            """
            Return an SSL wrapper around the given socket.

            This implementation only supports the socket to be wrapped and
            the server_side parameter.
            """
            return _ssl.wrap_socket(sock, server_side=server_side,
                                    **self.params)

    def create_ssl_context(client_side, cert=None, key=None, ca=None):
        """
        Create an SSL context using the given configuration.

        cert is a file to read a client certificate from; key is a file
        containing a private key corresponding to the certificate (if omitted,
        the key must be located in the certificate file); ca is a file
        containing trusted CA certificates (if this is given, the other side
        must authenticate itself).

        This implementation returns a shim object that only supports the
        wrap_socket() method with no parameters (but the socket to be
        wrapped), and is intended for ancient Python releases.
        """
        params = {}
        if cert is not None:
            params.update(certfile=cert, keyfile=key)
        if ca is not None:
            params.update(ca_certs=ca, cert_reqs=_ssl.CERT_REQUIRED)
        return SSLContextShim(params)
