# websocket_server -- WebSocket/HTTP server/client library
# https://github.com/CylonicRaider/websocket-server

"""
Support for "sessions" spanning multiple WebSocket connections.

In some (or many) cases, multiple WebSocket connections to the same URL are
(mostly) interchangeable. This module caters for that case by providing a
WebSocketSession class that transparently handles re-connecting to a WebSocket
endpoint, retrying commands whose results may have been missed, etc.

This module is NYI.
"""

import threading

from . import client
from .tools import MutexBarrier

__all__ = ['WebSocketSession']

SST_DISCONNECTED  = 'DISCONNECTED'
SST_CONNECTING    = 'CONNECTING'
SST_CONNECTED     = 'CONNECTED'
SST_DISCONNECTING = 'DISCONNECTING'

_SST_SUCCESSORS = {SST_DISCONNECTED : SST_CONNECTING   ,
                   SST_CONNECTING   : SST_CONNECTED    ,
                   SST_CONNECTED    : SST_DISCONNECTING,
                   SST_DISCONNECTING: SST_DISCONNECTED }
__all__.extend(_SST_SUCCESSORS)

class WebSocketSession(object):
    """
    WebSocketSession(url) -> new instance

    A "session" spanning multiple WebSocket connections. url is the WebSocket
    URL to connect to.

    Instance attributes are:
    url       : The URL to connect to. Initialized from the same-named
                constructor parameter. May be modified after instance creation
                to cause future connections to use that URL (but see
                reconnect() for a safer way of achieving that).

    Read-only instance attributes are:
    state     : The current connection state as one of the SST_* constants.
                One of DISCONNECTED -> CONNECTING -> CONNECTED ->
                DISCONNECTING -> DISCONNECTED ... (in that order). Reading
                this attribute is not particularly useful as it might be
                changed by another thread immediately afterwards.
    state_goal: The state this session is trying to achieve, as a SST_*
                constant.
    """

    def __init__(self, url):
        """
        __init__(url) -> None

        Instance initializer; see the class docstring for details.
        """
        self.url = url
        self.cond = threading.Condition()
        self.state = SST_DISCONNECTED
        self.state_goal = SST_DISCONNECTED
        self._conn_spinner = MutexBarrier()
        self._conn = None

    def __enter__(self):
        "Context manager entry; internal."
        self.cond.__enter__()

    def __exit__(self, *args):
        "Context manager exit; internal."
        self.cond.__exit__(*args)

    def _spin_connstates(self, state_goal, url=None, cycle=False):
        """
        _spin_connsates(state_goal, url=None, cycle=False) -> bool

        Internal method.

        This advances the current connection state, performing connects and
        disconnects as necessary, until state_goal is reached.

        state_goal is stored in the same-named instance attribute, which is
        used to determine when to return; the method parameter is used to
        determine the return value.

        url, if not None, is stored in the same-named instance attribute; the
        latter is used to connect to now and in the future.

        cycle, if true, suppresses an early return if the state_goal is
        already met, enabling reconnect() to function.

        Returns whether the state_goal as passed to this invocation was met
        at the time of the return (this might not be the case if multiple
        threads are invoking this method concurrently).
        """
        with self:
            self.state_goal = state_goal
            if url is not None: self.url = url
            if not cycle and self.state == self.state_goal: return True
        with self._conn_spinner:
            while 1:
                if self._conn_spinner.check():
                    with self:
                        self.state = _SST_SUCCESSORS[self.state]
                        if self.state == SST_CONNECTING:
                            func = self._do_connect
                        elif self.state == SST_DISCONNECTING:
                            func = self._do_disconnect
                    func()
                    self._conn_spinner.done()
                with self:
                    if self.state == state_goal:
                        return True

    def _do_connect(self):
        """
        _do_connect() -> None

        Actually establish a WebSocket connection and store it as an instance
        variable.

        The URL to connect to is taken from the "url" instance attribute and
        the resulting WebSocketFile object is stored in the "_conn" attribute.

        Concurrency note: This method is called without the internal lock held
        (but still serialized w.r.t. all other _do_connect()/_do_disconnect()
        calls); take care to synchronize on the internal lock (e.g. using
        "with self:") as needed.
        """
        # HACK: We assume that attribute access is atomic. Subclasses changing
        #       that should reimplement this method.
        self._conn = client.connect(self.url)

    def _do_disconnect(self):
        """
        _do_disconnect() -> None

        Actually disconnect the underlying WebSocket connection.

        This closes the WebSocketFile stored at the "_conn" attribute and
        resets the latter to None.

        See _do_connect() for concurrency notes.
        """
        with self:
            conn, self._conn = self._conn, None
        conn.close()

    def connect(self, url=None):
        """
        connect(url=None) -> bool

        Bring this session into the "connected" state, creating a WebSocket
        connection (which will be renewed if it breaks before the next
        disconnect() call) as necessary.

        url, if not None, replaces the same-named instance attribute and is
        used as the URL future connections (including the one initiated by
        this method, if any) go to.

        Returns when the connection is achieved (which may be immediately).

        Concurrency note: If multiple calls to connect() / reconnect() /
        disconnect() are active concurrently, they will "tug" at the state of
        the session towards their respective goals against each other. The
        session will transition between the connection states in their proper
        order in a well-defined manner and finally arrive at the state aimed
        at by the call to commence last. If a call is active without any
        others interferring, it will finish after the minimal amount of state
        transitions necessary; otherwise, it is unspecified at which points of
        this roundabout the individual calls will finish (and for how long it
        will continue overall), other than each call will return whether its
        goal state was in effect when it returned.
        """
        return self._spin_connstates(SST_CONNECTED, url=url)

    def reconnect(self, url=None):
        """
        reconnect(url=None) -> bool

        Bring this session into the "connected" state, forcing a
        disconnect-connect cycle if it is already connected. See the notes for
        connect() for more details.
        """
        return self._spin_connstates(SST_CONNECTED, url=url, cycle=True)

    def disconnect(self):
        """
        disconnect() -> bool

        Bring this session into the "disconnected" state, closing the internal
        WebSocket connection if necessary. See the notes for connect() (but
        in reverse) for more details.
        """
        return self._spin_connstates(SST_DISCONNECTED)
