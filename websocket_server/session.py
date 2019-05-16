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
from .tools import spawn_daemon_thread, Scheduler, Future, EOFQueue

__all__ = ['WebSocketSession', 'SST_IDLE', 'SST_DISCONNECTED',
           'SST_CONNECTING', 'SST_CONNECTED', 'SST_DISCONNECTING']

SST_IDLE          = 'IDLE'
SST_DISCONNECTED  = 'DISCONNECTED'
SST_CONNECTING    = 'CONNECTING'
SST_CONNECTED     = 'CONNECTED'
SST_DISCONNECTING = 'DISCONNECTING'

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
    state_goal: The state this session is trying to achieve, either
                SST_DISCONNECTED or SST_CONNECTED.
    conn      : The current WebSocket connection (if any) as a WebSocketFile.

    Class attributes (overridable on instances) are:
    USE_WTHREAD: Whether a background thread should be created for writing to
                 the underlying connection. If a thread is present, it is used
                 regardless of this setting; if it is not, writing operations
                 are performed by the threads that request them.
    """

    USE_WTHREAD = True

    def __init__(self, url, scheduler=None):
        """
        __init__(url, scheduler=None) -> None

        Instance initializer; see the class docstring for details.
        """
        if scheduler is None: scheduler = Scheduler()
        self.url = url
        self.scheduler = scheduler
        self.state = SST_IDLE
        self.state_goal = SST_DISCONNECTED
        self.conn = None
        self._cond = threading.Condition()
        self._scheduler_hold = scheduler.hold()
        self._rthread = None
        self._wthread = None

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
            if disconnect and self.state == SST_CONNECTED:
                # Wake up reader thread if it is busy reading messages; it
                # will eventually detach itself (if necessary), and signal
                # the writer thread to close itself.
                self._run_wthread(self._do_disconnect, self.conn, True)
            # Connect if told to; this amounts to spawning the reader thread
            # and letting it do its work.
            if connect:
                if self._rthread is None:
                    self._rthread = spawn_daemon_thread(self._rthread_main)
                if self._wthread is None and self.USE_WTHREAD:
                    queue = EOFQueue()
                    thr = spawn_daemon_thread(self._wthread_main, queue)
                    thr.queue = queue
                    self._wthread = thr

    def _rthread_main(self):
        """
        _rthread_main() -> None

        Internal method: Outermost code of the background thread responsible
        for reading WebSocket messages.
        """
        def keep_running(ignore_state=False):
            "Return whether this reader thread should keep running."
            return (self._rthread == this_thread and
                    (ignore_state or self.state_goal == SST_CONNECTED))
        this_thread = threading.current_thread()
        conn = None
        try:
            while 1:
                # Connect.
                with self:
                    if not keep_running(): return
                    self.state = SST_CONNECTING
                    params = self._conn_params()
                conn = self._do_connect(**params)
                with self:
                    if not keep_running(): return
                    new_params = self._conn_params()
                    self.state = SST_CONNECTED
                    self.conn = conn
                # Read messages (unless we should reconnect immediately).
                if new_params == params:
                    self._do_read_loop(conn)
                # Disconnect.
                with self:
                    if not keep_running(True): return
                    self.state = SST_DISCONNECTING
                    self.conn = None
                self._do_disconnect(conn)
                with self:
                    if not keep_running(True): return
                    self.state = SST_DISCONNECTED
        finally:
            with self:
                if self._rthread is this_thread:
                    self.state = SST_IDLE
                    self.conn = None
                    self._rthread = None
                    if self._wthread is not None:
                        self._wthread.queue.close()
                        self._wthread = None
            if conn is not None:
                self._do_disconnect(conn)

    def _wthread_main(self, queue):
        """
        _wthread_main(queue) -> None

        Internal method: Main function of the (optional) background thread
        responsible for writing to the underlying WebSocket.

        queue is an EOFQueue yielding callbacks to be called by this thread.
        The callbacks take no arguments and their return values are ignored.
        """
        this_thread = threading.current_thread()
        try:
            while 1:
                try:
                    cb = queue.get()
                except EOFError:
                    break
                cb()
        finally:
            with self:
                if self._wthread is this_thread:
                    self._wthread = None

    def _conn_params(self):
        """
        _conn_params() -> dict

        Gather the parameters necessary to establish a new connection and
        return them.

        The parameters are passed as keyword arguments to _do_connect();
        subclasses overriding this method must therefore override
        _do_connect() as well.

        Concurrency note: This method is called with the internal monitor lock
        held and should therefore finish quickly.
        """
        return {'url': self.url}

    def _do_connect(self, url):
        """
        _do_connect(url) -> WebSocketFile

        Actually establish a WebSocket connection and return it. url is the
        WebSocket URL to connect to; overriding methods may specify additional
        parameters.

        Concurrency note: This method is called with no locks held; attribute
        accesses should be protected via "with self:" as necessary. However,
        values that require a new connection when they change (such as the
        URL) should be retrieved in _conn_params() instead; see there for
        more details.
        """
        return client.connect(url)

    def _do_read_loop(self, conn):
        """
        _do_read_loop(conn) -> None

        Repeatedly read frames from the given WebSocket connection and submit
        closures processing them via the _handle_raw() method to the
        scheduler.
        """
        scheduler = self.scheduler
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

    def _do_disconnect(self, conn, asynchronous=False):
        """
        _do_disconnect(conn, asynchronous=False) -> None

        Actually disconnect the given WebSocket connection. conn is the
        WebSocket connection to close. asynchronous tells whether this close
        is initiated from the thread responsible for reading messages (False)
        or to interrupt a connection ongoing concurrently (True).

        Concurrency note: As this method may be called to interrupt an ongoing
        connection, it should be particularly cautious about thread safety.
        """
        conn.close(wait=(not asynchronous))

    def _run_wthread(self, func, *args, **kwds):
        """
        _run_wthread(func, *args, **kwds) -> Future

        Schedule the given callback to be executed in the writer thread, if
        there is any. If there is no reader thread, func is executed
        synchronously. args and kwds are passed to func as positional and
        keyword arguments, respectively; func's return value is wrapped by
        the returned Future.
        """
        ret = Future(lambda: cb(*args, **kwds))
        with self:
            wthread_present = (self._wthread is not None)
            if wthread_present:
                self._wthread.queue.put(ret.run)
        if not wthread_present:
            ret.run()
        return ret

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
