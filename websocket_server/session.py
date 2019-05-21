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

import time
import threading

from . import client
from .tools import spawn_daemon_thread, Future, EOFQueue

__all__ = ['SST_IDLE', 'SST_DISCONNECTED', 'SST_CONNECTING', 'SST_CONNECTED',
           'SST_INTERRUPTED', 'SST_DISCONNECTING', 'ERRS_RTHREAD',
           'ERRS_CONNECT', 'ERRS_READ', 'ERRS_WRITE', 'backoff_constant',
           'backoff_linear', 'backoff_exponential', 'WebSocketSession']

SST_IDLE          = 'IDLE'
SST_DISCONNECTED  = 'DISCONNECTED'
SST_CONNECTING    = 'CONNECTING'
SST_CONNECTED     = 'CONNECTED'
SST_INTERRUPTED   = 'INTERRUPTED'
SST_DISCONNECTING = 'DISCONNECTING'

ERRS_RTHREAD = 'rthread'
ERRS_CONNECT = 'connect'
ERRS_READ    = 'read'
ERRS_WRITE   = 'write'

def backoff_constant(n):
    """
    backoff_constant(n) -> float

    Linear backoff implementation. This returns the constant 1.

    See WebSocketSession for details.
    """
    return 1

def backoff_linear(n):
    """
    backoff_linear(n) -> float

    Quadratic backoff implementation. This returns n.

    See WebSocketSession for details.
    """
    return n

def backoff_exponential(n):
    """
    backoff_exponential(n) -> float

    Exponential backoff implementation. This returns 2 ** n.

    See WebSocketSession for details.
    """
    return 2 ** n

class WebSocketSession(object):
    """
    WebSocketSession(url, backoff=None) -> new instance

    A "session" spanning multiple WebSocket connections. url is the WebSocket
    URL to connect to; backoff is the backoff algorithm to use (see below),
    defaulting to the module-level backoff_linear() function.

    Instance attributes are:
    url    : The URL to connect to. Initialized from the same-named
             constructor parameter. May be modified after instance creation to
             cause future connections to use that URL (but see reconnect() for
             a safer way of achieving that).
    backoff: The connection backoff algorithm to use. Initialized from the
             same-named constructor parameter. This is a function mapping an
             integer to a floating value; the parameter is the (zero-based)
             index of the current connection attempt (that has failed), while
             the return value is the time (in seconds) to wait until the next
             connection attempt. The index is reset when a connection attempt
             succeeds. The backoff_*() module-level functions provide a few
             ready-to-use implementations to plug into this.

    Read-only instance attributes are:
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

    Error handling note: The on_*() callback methods are not shielded against
    errors in overridden implementations; exceptions raised in them may bring
    the connection into an inconsistent state.
    """

    USE_WTHREAD = True

    def __init__(self, url, backoff=None):
        """
        __init__(url, backoff=None) -> None

        Instance initializer; see the class docstring for details.
        """
        if backoff is None: backoff = backoff_linear
        self.url = url
        self.backoff = backoff
        self.state = SST_IDLE
        self.state_goal = SST_DISCONNECTED
        self.conn = None
        self._cond = threading.Condition()
        self._rthread = None
        self._wthread = None
        self._wqueue = None
        self._connected = None
        self._disconnected = None
        self._disconnect_ok = False

    def __enter__(self):
        "Context manager entry; internal."
        self._cond.__enter__()

    def __exit__(self, *args):
        "Context manager exit; internal."
        self._cond.__exit__(*args)

    def _sleep(self, timeout, check=None):
        """
        _sleep(timeout, check=None) -> None

        Wait for a specified time while some condition holds. timeout is the
        time to wait for in (potentially fractional) seconds; check is a
        function taking no arguments and returning whether to continue
        sleeping, defaulting to always sleeping on.

        The sleep is based on the internal condition variable and can be
        interrupted by notifying it.
        """
        if check is None: check = lambda: True
        deadline = time.time() + check
        with self:
            while check():
                now = time.time()
                if now > deadline: break
                self._cond.wait(deadline - now)

    def _cycle_connstates(self, disconnect=False, connect=False, url=None,
                          disconnect_ok=False):
        """
        _cycle_connstates(disconnect=False, connect=False, url=None,
                          disconnect_ok=False) -> Future

        Internal method backing connect() etc. If disconnect is true, performs
        a disconnect; if connect is true, performs a connect. url, if not
        None, is stored in the same-named instance attribute. disconnect_ok
        is only meaningful when disconnect is specified, and tells whether the
        disconnect is regular (True) or due to some error (False); it is
        passed on to the corresponding life cycle callbacks. Returns a Future
        that will resolve (to some unspecified value) when the requested
        operations are done (which may be immediately).

        The "state_goal" instance attribute is set to SST_CONNECTED if connect
        is true, otherwise to SST_DISCONNECTED if disconnect is true,
        otherwise it is unmodified.
        """
        def disconnect_cb():
            self.on_disconnecting(connect, disconnect_ok)
            self._do_disconnect(disconnect_conn, True)
        disconnect_conn = None
        with self:
            # Update attributes; prepare return value.
            if connect:
                self.state_goal = SST_CONNECTED
                if self.state == SST_CONNECTED:
                    ret = Future.resolved()
                else:
                    if self._connected is None:
                        self._connected = Future()
                    ret = self._connected
            elif disconnect:
                self.state_goal = SST_DISCONNECTED
                if self.state == SST_DISCONNECTED:
                    ret = Future.resolved()
                else:
                    if self._disconnected is None:
                        self._disconnected = Future()
                    ret = self._disconnected
            else:
                ret = Future.resolved()
            if url is not None:
                self.url = url
            if disconnect:
                self._disconnect_ok = disconnect_ok
            # Disconnect if told to.
            if disconnect:
                if self.state == SST_CONNECTING:
                    # Wake up potentially sleeping reader thread.
                    self._cond.notifyAll()
                elif self.state == SST_CONNECTED:
                    self.state = SST_INTERRUPTED
                    # Ensure the reader thread will be eventually woken.
                    disconnect_conn = self.conn
            # Connect if told to; this amounts to spawning the reader thread
            # and letting it do its work.
            if connect:
                if self._rthread is None:
                    self._rthread = spawn_daemon_thread(self._rthread_main)
                if self._wthread is None and self.USE_WTHREAD:
                    self._wqueue = EOFQueue()
                    self._wthread = spawn_daemon_thread(self._wthread_main,
                                                        self._wqueue)
        if disconnect_conn is not None:
            self._run_wthread(disconnect_cb)
        return ret

    def _rthread_main(self):
        """
        _rthread_main() -> None

        Internal method: Outermost code of the background thread responsible
        for reading WebSocket messages.
        """
        def detach(do_disconnect=True):
            "Clean up instance state pointing at the existence of this thread"
            with self:
                if self._rthread is not this_thread: return
                self.state = SST_IDLE
                self._rthread = None
                self.conn = None
                if self._wthread is not None:
                    self._wqueue.close()
                    self._wthread = None
                    self._wqueue = None
            if conn is not None and do_disconnect:
                self._do_disconnect(conn)
        def sleep_check():
            # Run in an implicit "with self:" block.
            return (self.state_goal == SST_CONNECTED)
        this_thread = threading.current_thread()
        conn = None
        transient = False
        conn_attempt = 0
        try:
            while 1:
                # Prepare for connecting or detach.
                with self:
                    # Detach if requested.
                    if self.state_goal != SST_CONNECTED:
                        detach(False)
                        break
                    self.state = SST_CONNECTING
                    if self._connected is None:
                        self._connected = Future()
                    params = self._conn_params()
                # Connect.
                self.on_connecting(transient)
                try:
                    conn = self._do_connect(**params)
                except Exception as exc:
                    self.on_error(exc, ERRS_CONNECT, True)
                    self._sleep(self.backoff(conn_attempt), sleep_check)
                    conn_attempt += 1
                    continue
                else:
                    conn_attempt = 0
                # Done connecting.
                with self:
                    new_params = self._conn_params()
                    do_read = (new_params == params)
                    if self.state_goal == SST_CONNECTED:
                        self._disconnect_ok = True
                    else:
                        do_read = False
                    self.state = SST_CONNECTED
                    self.conn = conn
                    self._connected.set()
                    self._connected = None
                self.on_connected(transient)
                # Read messages (unless we should disconnect immediately).
                if do_read:
                    self._do_read_loop(conn)
                # Prepare for disconnecting.
                with self:
                    run_dc_hook = (self.state != SST_INTERRUPTED)
                    transient = (self.state_goal == SST_CONNECTED)
                    ok = self._disconnect_ok
                    self.state = SST_DISCONNECTING
                    self.conn = None
                    if self._disconnected is None:
                        self._disconnected = Future()
                # Disconnect.
                if run_dc_hook:
                    self.on_disconnecting(transient, ok)
                self._do_disconnect(conn)
                conn = None
                # Done disconnecting.
                with self:
                    self.state = SST_DISCONNECTED
                    self._disconnected.set()
                    self._disconnected = None
                self.on_disconnected(transient, ok)
        except Exception as exc:
            self.on_error(exc, ERRS_RTHREAD)
        finally:
            detach()

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
                try:
                    cb()
                except Exception as exc:
                    self.on_error(exc, ERRS_WRITE)
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

        Repeatedly read frames from the given WebSocket connection and pass
        them into on_message; on EOF, return (without calling on_message).
        """
        while 1:
            try:
                frame = conn.read_frame()
            except Exception as exc:
                self.on_error(exc, ERRS_READ)
            if frame is None: break
            self.on_message(frame)

    def _do_send(self, conn, data):
        """
        _do_send(conn, data) -> None

        Backend of the send_message() method. This (synchronously) submits
        data into the WebSocketFile conn using an appropriate frame type.
        """
        if isinstance(data, bytes):
            conn.write_binary_frame(data)
        else:
            conn.write_text_frame(data)

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

    def _run_wthread(self, cb, check_state=None):
        """
        _run_wthread(cb, check_state=None) -> Future or None

        Schedule the given callback to be executed in the writer thread. cb
        is the callback to run. check_state, if not None, indicates that only
        the given state may be in effect while submitting the callback; if the
        state does not match, None is returned and cb is not run. Otherwise,
        this returns a Future wrapping the return value of the callback.

        If there is no reader thread (but check_state is satisfied), cb is
        executed synchronously.
        """
        ret = Future(cb)
        with self:
            if check_state is not None and self.state != check_state:
                return None
            queue = self._wqueue
            if queue is not None:
                queue.put(ret.run)
        if queue is None:
            ret.run()
        return ret

    def on_connecting(self, transient):
        """
        on_connecting(transient) -> None

        Callback invoked before a connection is established. transient tells
        whether this is part of a reconnect (True) or an "initial" connect
        (False).
        """
        pass

    def on_connected(self, transient):
        """
        on_connect(transient) -> None

        Callback invoked when a connection is established. transient tells
        whether this is part of a reconnect (True) or an "initial" connect
        (False).
        """
        pass

    def on_message(self, msg):
        """
        on_message(msg) -> None

        Callback invoked when a WebSocket message arrives. msg is a
        wsfile.Message containing the data that were received.
        """
        pass

    def on_disconnecting(self, transient, ok):
        """
        on_disconnecting(transient, ok) -> None

        Callback invoked when a connection is about to be closed. transient
        tells whether this is part of a reconnect (True) or a "final" close
        (False); ok tells whether the disconnect was "regular" (True) rather
        than caused by some sort of error (False).
        """
        pass

    def on_disconnected(self, transient, ok):
        """
        on_disconnect(transient, ok) -> None

        Callback invoked when a connection has been closed. transient tells
        whether this is part of a reconnect (True) or a "final" close (False);
        ok tells whether the disconnect was "regular" (True) rather than
        caused by some sort of error (False).
        """
        pass

    def on_error(self, exc, source, swallow=False):
        """
        on_error(exc, source, swallow=False) -> None

        Callback invoked when an error occurs somewhere. exc is the exception
        object (sys.exc_info() can be used to retrieve more information about
        the error); source is a ERRS_* constant indicating in which component
        the error originated; swallow tells whether the exception should be
        suppressed (rather than being re-raised).

        The default implementation does nothing aside from re-raising the
        exception (if told to); other implementations could make more
        fine-grained decisions based on, e.g., the type of the exception and
        the source.
        """
        if not swallow: raise

    def send_message(self, data):
        """
        send_message(data) -> Future

        Send a WebSocket frame containing the given data. The type of frame is
        chosen automatically depending on whether data is a byte or Unicode
        string. The send is asynchronous; this returns a Future that resolves
        when it finishes.

        In order to send messages, the session must be in the CONNECTED state;
        if it is not, an exception is raised.
        """
        ret = self._run_wthread(lambda: self._do_send(self.conn, data),
                                SST_CONNECTED)
        if ret is None:
            raise ValueError('Cannot send to non-connected WebSocketSession')
        return ret

    def connect_async(self, url=None):
        """
        disconnect_async(url=None) -> Future

        Bring this session into the "connected" state, creating a WebSocket
        connection as necessary.

        This is the asynchronous version of connect(); see there for more
        details. This method returns while the actual connection attempt
        proceeds in the background; in order to wait for the connection to
        complete, wait() on the returned Future.
        """
        return self._cycle_connstates(connect=True, url=url)

    def reconnect_async(self, url=None, ok=True):
        """
        reconnect_async(url=None, ok=True) -> Future

        Bring this session into the "connected" state, forcing a
        disconnect-connect cycle if it is already connected.

        This is the asynchronous version of reconnect(); see there for more
        details. This method returns while the actual operation proceeds in
        the background; in order to wait for it to complete, wait() on the
        returned Future.
        """
        return self._cycle_connstates(disconnect=True, connect=True, url=url,
                                      disconnect_ok=ok)

    def disconnect_async(self, ok=True):
        """
        disconnect(ok=True) -> Future

        Bring this session into the "disconnected" state, closing the internal
        WebSocket connection if necessary.

        This is the asynchronous version of disconnect(); see there for more
        details. This method returns while the actual disconnect proceeds in
        the background; in order to wait for the disconnect to complete,
        wait() on the returned Future.
        """
        return self._cycle_connstates(disconnect=True, disconnect_ok=ok)

    def connect(self, *args, **kwds):
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

        This is the blocking version of connect_async().
        """
        return self.connect_async(*args, **kwds).wait()

    def reconnect(self, *args, **kwds):
        """
        reconnect(url=None, ok=True) -> None

        Bring this session into the "connected" state, forcing a
        disconnect-connect cycle if it is already connected.

        See the notes for disconnect() and connect() for more details. This is
        the blocking version of reconnect_async().
        """
        return self.reconnect_async(*args, **kwds).wait()

    def disconnect(self, *args, **kwds):
        """
        disconnect(ok=True) -> None

        Bring this session into the "disconnected" state, closing the internal
        WebSocket connection if necessary.

        ok tells whether the close is normal (True) or caused by some sort of
        error (False).

        See the notes for connect() (but in reverse) for more details. This is
        the blocking version of disconnect_async().
        """
        return self.disconnect_async(*args, **kwds).wait()
