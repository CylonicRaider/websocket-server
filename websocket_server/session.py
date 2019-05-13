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
from .tools import spawn_daemon_thread, Scheduler

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
    WebSocketSession(url, scheduler=None) -> new instance

    A "session" spanning multiple WebSocket connections. url is the WebSocket
    URL to connect to.

    Instance attributes are:
    url: The URL to connect to. Initialized from the same-named constructor
         parameter. May be modified after instance creation to cause future
         connections to use that URL (but see reconnect() for a safer way of
         achieving that).

    Read-only instance attributes are:
    scheduler : The Scheduler instance executing callbacks. If not set via the
                same-named constructor parameter, a new instance is created.
    state     : The current connection state as one of the SST_* constants.
                Reading this attribute is not particularly useful as it might
                be changed by another thread immediately afterwards.
    state_goal: The state this session is trying to achieve, as a SST_*
                constant.
    conn      : The current WebSocket connection (if any) as a WebSocketFile.
    """

    def __init__(self, url, scheduler=None):
        """
        __init__(url, scheduler=None) -> None

        Instance initializer; see the class docstring for details.
        """
        if scheduler is None: scheduler = Scheduler()
        self.url = url
        self.scheduler = scheduler
        self.state = SST_DISCONNECTED
        self.state_goal = SST_DISCONNECTED
        self.conn = None
        self._cond = threading.Condition()
        self._conn_spinner = MutexBarrier()
        self._scheduler_hold = scheduler.hold()
        self._rthread = None

    def __enter__(self):
        "Context manager entry; internal."
        self._cond.__enter__()

    def __exit__(self, *args):
        "Context manager exit; internal."
        self._cond.__exit__(*args)

    def _cycle_connstates(self, disconnect=False, connect=False, url=None):
        """
        _cycle_connstates(disconnect=False, connect=False, url=None) -> None

        Internal method backing connect() etc. If disconnect is true, performs
        a disconnect; if connect is true, performs a connect. url, if not
        None, is stored in the same-named instance attribute. The "state_goal"
        instance attribute is set to SST_CONNECTED if connect is true,
        otherwise to SST_DISCONNECTED if disconnect is true, otherwise it is
        unmodified.
        """
        with self:
            # Update attributes.
            if connect:
                self.state_goal = SST_CONNECTED
            elif disconnect:
                self.state_goal = SST_DISCONNECTED
            if url is not None:
                self.url = url
            # Disconnect if told to.
            if disconnectand and self.state == SST_CONNECTED:
                # Wake up reader thread if it is busy reading messages; it
                # will eventually detach itself.
                self._do_disconnect(True)
            # Connect if told to; this amounts to spawning the reader thread
            # and letting it do its work.
            if connect and self._rthread is None:
                self._rthread = spawn_daemon_thread(self._rthread_main)

    def _rthread_main(self):
        """
        _rthread_main() -> None

        Internal method: Outermost code of the background thread responsible
        for reading WebSocket messages.
        """
        def keep_running():
            "Return whether this reader thread should keep running."
            return (self._rthread == this_thread and
                    self.state_goal == SST_CONNECTED)
        this_thread = threading.current_thread()
        try:
            while 1:
                # Connect.
                with self:
                    if not keep_running(): return
                    self.state = SST_CONNECTING
                self._do_connect()
                with self:
                    if not keep_running(): return
                    self.state = SST_CONNECTED
                # Read messages.
                self._do_read_loop()
                # Disconnect.
                with self:
                    if not keep_running(): return
                    self.state = SST_DISCONNECTING
                self._do_disconnect()
                with self:
                    if not keep_running(): return
                    self.state = SST_DISCONNECTED
        finally:
            with self:
                if self._rthread is this_thread:
                    if self.conn is not None:
                        self._do_disconnect()
                    self.state = SST_DISCONNECTED
                    self._rthread = None

    def _do_connect(self):
        """
        _do_connect() -> None

        Actually establish a WebSocket connection and store it as an instance
        variable.

        The URL to connect to is taken from the "url" instance attribute and
        the resulting WebSocketFile object is stored in the "conn" attribute.

        Concurrency note: This method is called with no locks held; attribute
        accesses should be protected via "with self:" as necessary.
        """
        with self:
            url = self.url
        conn = client.connect(url)
        with self:
            self.conn = conn

    def _do_read_loop(self):
        """
        _do_read_loop() -> None

        Repeatedly read frames from the underlying WebSocket connection and
        submit them to the scheduler for processing.
        """
        conn, scheduler = self.conn, self.scheduler
        while 1:
            frame = conn.read_frame()
            if frame is None: break
            scheduler.add_now(lambda f=frame: self._handle_raw(f))

    def _handle_raw(self, frame):
        """
        _handle_raw(frame) -> None

        Handle a frame received from the WebSocket. This method is invoked in
        the scheduler.
        """
        pass # NYI

    def _do_disconnect(self, asynchronous=False):
        """
        _do_disconnect(asynchronous=False) -> None

        Actually disconnect the underlying WebSocket connection. asynchronous
        tells whether this close is initiated from the thread responsible for
        reading messages (False) or to interrupt a connection ongoing
        concurrently (True).

        This closes the WebSocketFile stored at the "conn" attribute, and
        resets the latter to None if asynchronous is false.

        Concurrency note: As this method may be called to interrupt an ongoing
        connection, it should be particularly cautious about thread safety.
        """
        with self:
            conn = self.conn
            if not asynchronous: self.conn = None
        if conn is not None:
            conn.close()

    def connect(self, url=None):
        """
        connect(url=None) -> None

        Bring this session into the "connected" state, creating a WebSocket
        connection (which will be renewed if it breaks before the next
        disconnect() call) as necessary.

        url, if not None, replaces the same-named instance attribute and is
        used as the URL future connections (including the one initiated by
        this method, if any) go to. If a connect is going on concurrently,
        it may or may not be redone in order to apply the new URL.

        Concurrency note: connect() / reconnect() / disconnect() initiate
        asynchronous actions and return quickly. If multiple calls are
        submitted in rapid succession, the effects of individual calls may be
        superseded by others or elided. Eventually, the last call (i.e. the
        last to acquire the internal synchronization lock) will prevail.
        """
        self._cycle_connstates(connect=True, url=url)

    def reconnect(self, url=None):
        """
        reconnect(url=None) -> None

        Bring this session into the "connected" state, forcing a
        disconnect-connect cycle if it is already connected. See the notes for
        connect() for more details.
        """
        self._cycle_connstates(disconnect=True, connect=True, url=url)

    def disconnect(self):
        """
        disconnect() -> None

        Bring this session into the "disconnected" state, closing the internal
        WebSocket connection if necessary. See the notes for connect() (but
        in reverse) for more details.
        """
        self._cycle_connstates(disconnect=True)
