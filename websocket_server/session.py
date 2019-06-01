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
import collections
import uuid
import threading

from . import client
from .tools import spawn_daemon_thread, Scheduler, Future, EOFQueue

__all__ = ['SST_IDLE', 'SST_DISCONNECTED', 'SST_CONNECTING', 'SST_CONNECTED',
           'SST_INTERRUPTED', 'SST_DISCONNECTING',
           'CST_NEW', 'CST_SENDING', 'CST_SENT', 'CST_CONFIRMED',
           'ERRS_RTHREAD', 'ERRS_CONNECT', 'ERRS_READ', 'ERRS_WRITE',
           'ERRS_SCHEDULER',
           'backoff_constant', 'backoff_linear', 'backoff_exponential',
           'ReconnectingWebSocket', 'WebSocketSession']

SST_IDLE          = 'IDLE'
SST_DISCONNECTED  = 'DISCONNECTED'
SST_CONNECTING    = 'CONNECTING'
SST_CONNECTED     = 'CONNECTED'
SST_INTERRUPTED   = 'INTERRUPTED'
SST_DISCONNECTING = 'DISCONNECTING'

CST_NEW       = 'NEW'
CST_SENDING   = 'SENDING'
CST_SENT      = 'SENT'
CST_CONFIRMED = 'CONFIRMED'

ERRS_RTHREAD   = 'rthread'
ERRS_CONNECT   = 'connect'
ERRS_READ      = 'read'
ERRS_WRITE     = 'write'
ERRS_SCHEDULER = 'scheduler'

def run_cb(_func, *_args, **_kwds):
    """
    run_cb(func, *args, **kwds) -> any or None

    If func is not None, return the result of calling it with the given
    arguments; otherwise, do nothing and return None.
    """
    if _func is not None: return _func(*_args, **_kwds)

def run_async(_func, _wait, *_args, **_kwds):
    """
    run_async(func, wait, *args, **kwds) -> Future

    Convenience function that runs func(*args, **kwds) and optionally (i.e. if
    wait is true) wait()s on the return value before re-returning it.
    """
    ret = _func(*_args, **_kwds)
    if _wait: ret.wait()
    return ret

def backoff_constant(n):
    """
    backoff_constant(n) -> float

    Linear backoff implementation. This returns the constant 1.

    See ReconnectingWebSocket for details.
    """
    return 1

def backoff_linear(n):
    """
    backoff_linear(n) -> float

    Quadratic backoff implementation. This returns n.

    See ReconnectingWebSocket for details.
    """
    return n

def backoff_exponential(n):
    """
    backoff_exponential(n) -> float

    Exponential backoff implementation. This returns 2 ** n.

    See ReconnectingWebSocket for details.
    """
    return 2 ** n

class ReconnectingWebSocket(object):
    """
    ReconnectingWebSocket(url, protos=None) -> new instance

    An automatically reconnecting WebSocket wrapper. url is the WebSocket
    URL to connect to. protos is an indication on which WebSocket subprotocols
    may be used.

    Instance attributes are:
    url    : The URL to connect to. Initialized from the same-named
             constructor parameter. May be modified after instance creation to
             cause future connections to use that URL (but see reconnect() for
             a safer way of achieving that).
    protos : Which WebSocket subprotocols may be used. May be None, a single
             string, or a list of strings. See client.connect() for more
             details.
    backoff: The connection backoff algorithm to use. Defaults to
             backoff_linear(). This is a function mapping an integer to a
             floating value; the parameter is the (zero-based) index of the
             current connection attempt (that has failed), while the return
             value is the time (in seconds) to wait until the next connection
             attempt. The index is reset when a connection attempt succeeds.
             The backoff_*() module-level functions provide a few ready-to-use
             implementations to plug into this.

    For various events (see the on_*() methods), callbacks can be specified
    via the correpondingly-named *_cb instance attributes; the callbacks (if
    not None) are called with the same arguments as the event handler methods
    (excluding the "self" argument) by the event handlers' default
    implementations. Overriding methods are strongly advised to call the
    parent class' implementation to preserve this behavior (but see also
    on_error()).

    Read-only instance attributes are:
    state     : The current connection state as one of the SST_* constants.
                Reading this attribute is not particularly useful as it might
                be changed by another thread immediately afterwards.
    state_goal: The state this ReconnectingWebSocket is trying to achieve,
                either SST_DISCONNECTED or SST_CONNECTED.
    conn      : The current WebSocket connection (if any) as a WebSocketFile.

    Class attributes (overridable on instances) are:
    USE_WTHREAD: Whether a background thread should be created for writing to
                 the underlying connection. If a thread is present, it is used
                 regardless of this setting; if it is not, writing operations
                 are performed by the threads that request them.

    Note that this is not a drop-in replacement for the WebSocketFile class.

    Error handling note: The on_*() event handler methods and various
    callbacks are not shielded against errors in overridden implementations;
    exceptions raised in them may bring the connection into an inconsistent
    state.
    """

    USE_WTHREAD = True

    def __init__(self, url, protos=None):
        """
        __init__(url, protos=None) -> None

        Instance initializer; see the class docstring for details.
        """
        self.url = url
        self.protos = protos
        self.backoff = backoff_linear
        self.connecting_cb = None
        self.connected_cb = None
        self.message_cb = None
        self.disconnecting_cb = None
        self.disconnected_cb = None
        self.error_cb = None
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
        passed on to the corresponding life cycle event handlers. Returns a
        Future that will resolve (to some unspecified value) when the
        requested operations are done (which may be immediately).

        The "state_goal" instance attribute is set to SST_CONNECTED if connect
        is true, otherwise to SST_DISCONNECTED if disconnect is true,
        otherwise it is unmodified.
        """
        def disconnect_cb():
            self.on_disconnecting(disconnect_conn.id, connect, disconnect_ok)
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
                    if self._connected is not None:
                        self._connected.set()
                        self._connected = None
                self.on_connected(conn.id, transient)
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
                # Disconnect.
                if run_dc_hook:
                    self.on_disconnecting(conn.id, transient, ok)
                self._do_disconnect(conn)
                conn = None
                # Done disconnecting.
                with self:
                    self.state = SST_DISCONNECTED
                    if self._disconnected is not None:
                        self._disconnected.set()
                        self._disconnected = None
                self.on_disconnected(conn.id, transient, ok)
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
        return {'url': self.url, 'protos': self.protos}

    def _do_connect(self, url, protos):
        """
        _do_connect(url, protos) -> WebSocketFile

        Actually establish a WebSocket connection and return it. url is the
        WebSocket URL to connect to. protos is an indication on which
        subprotocols to use (see the same-named instance attribute for
        details). Overriding methods may specify additional parameters.

        The return value is expected to be a valid WebSocketFile with an "id"
        attribute containing a comparable and hashable object that uniquely
        identifies the connection. This implementation uses a random (version
        4) UUID.

        Concurrency note: This method is called with no locks held; attribute
        accesses should be protected via "with self:" as necessary. However,
        values that require a new connection when they change (such as the
        URL) should be retrieved in _conn_params() instead; see there for
        more details.
        """
        conn = client.connect(url, protos)
        conn.id = uuid.uuid4()
        return conn

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
            self.on_message(frame, conn.id)

    def _do_send(self, conn, data, before_cb, after_cb):
        """
        _do_send(conn, data) -> None

        Backend of the send_message() method. This (synchronously) submits
        data into the WebSocketFile conn using an appropriate frame type and
        invokes the given callbacks.
        """
        if before_cb is not None:
            before_cb()
        if isinstance(data, bytes):
            conn.write_binary_frame(data)
        else:
            conn.write_text_frame(data)
        if after_cb is not None:
            after_cb()

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

        Event handler method invoked before a connection is established.
        transient tells whether this is part of a reconnect (True) or an
        "initial" connect (False). Since the connection is not established
        yet, no ID is provided.

        The default implementation invokes the corresponding callback; see the
        class docstring for details.
        """
        run_cb(self.connecting_cb, transient)

    def on_connected(self, connid, transient):
        """
        on_connect(connid, transient) -> None

        Event handler method invoked when a connection is established.
        connid is the ID of the connection. transient tells whether this is
        part of a reconnect (True) or an "initial" connect (False).

        The default implementation invokes the corresponding callback; see the
        class docstring for details.
        """
        run_cb(self.connected_cb, connid, transient)

    def on_message(self, msg, connid):
        """
        on_message(msg, connid) -> None

        Event handler method invoked when a WebSocket message arrives. msg is
        a wsfile.Message containing the data that were received. connid is the
        ID of the connection the message was received from.

        The default implementation invokes the corresponding callback; see the
        class docstring for details.
        """
        run_cb(self.message_cb, msg, connid)

    def on_disconnecting(self, connid, transient, ok):
        """
        on_disconnecting(connid, transient, ok) -> None

        Event handler method invoked when a connection is about to be closed.
        connid is the ID of the connection. transient tells whether this is
        part of a reconnect (True) or a "final" close (False). ok tells
        whether the disconnect was "regular" (True) rather than caused by some
        sort of error (False).

        The default implementation invokes the corresponding callback; see the
        class docstring for details.
        """
        run_cb(self.disconnecting_cb, connid, transient, ok)

    def on_disconnected(self, connid, transient, ok):
        """
        on_disconnect(connid, transient, ok) -> None

        Event handler method invoked when a connection has been closed.
        connid is the ID of the connection. transient tells whether this is
        part of a reconnect (True) or a "final" close (False). ok tells
        whether the disconnect was "regular" (True) rather than caused by some
        sort of error (False).

        The default implementation invokes the corresponding callback; see the
        class docstring for details.
        """
        run_cb(self.disconnected_cb, connid, transient, ok)

    def on_error(self, exc, source, swallow=False):
        """
        on_error(exc, source, swallow=False) -> None

        Event handler method invoked when an error occurs somewhere. exc is
        the exception object (sys.exc_info() can be used to retrieve more
        information about the error); source is a ERRS_* constant indicating
        in which component the error originated; swallow tells whether the
        exception should be suppressed (rather than being re-raised).

        The default implementation does nothing aside from invoking the
        corresponding callback (see the class docstring for details) and
        re-raising the exception if told to.
        Other implementations could make more fine-grained decisions based on,
        e.g., the type of the exception and the source. See also the
        module-level run_cb() convenience function.
        """
        run_cb(self.error_cb, exc, source, swallow)
        if not swallow: raise

    def send_message(self, data, before_cb=None, after_cb=None):
        """
        send_message(data, before_cb=None, after_cb=None) -> Future

        Send a WebSocket frame containing the given data. The type of frame is
        chosen automatically depending on whether data is a byte or Unicode
        string. The send is asynchronous; this returns a Future that resolves
        when it finishes. before_cb is invoked (if not None and with no
        arguments) immediately before sending the message, after_cb (with the
        same notes as before_cb) is invoked immediately after sending it.

        In order to send messages, the instance must be in the CONNECTED
        state; if it is not, an exception is raised. All sends and callbacks
        (on the same ReconnectingWebSocket) are serialized w.r.t. each other
        (in particular, a message's after_cb is invoked before the next one's
        before_cb).
        """
        ret = self._run_wthread(lambda: self._do_send(self.conn, data,
            before_cb, after_cb), SST_CONNECTED)
        if ret is None:
            raise ValueError('Cannot send to non-connected '
                'ReconnectingWebSocket')
        return ret

    def connect(self, url=None):
        """
        connect(url=None) -> Future

        Bring this instance into the "connected" state, creating a WebSocket
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
        last to acquire the internal synchronization lock) will prevail. In
        order to wait for the connection to finish, call the returned Future's
        wait() method.
        """
        return self._cycle_connstates(connect=True, url=url)

    def reconnect(self, url=None, ok=True):
        """
        reconnect(url=None, ok=True) -> Future

        Bring this instance into the "connected" state, forcing a
        disconnect-connect cycle if it is already connected.

        See the notes for connect() and disconnect() for more details.
        """
        return self._cycle_connstates(disconnect=True, connect=True, url=url,
                                      disconnect_ok=ok)

    def disconnect(self, ok=True):
        """
        disconnect(ok=True) -> Future

        Bring this instance into the "disconnected" state, closing the
        internal WebSocket connection if necessary.

        ok tells whether the close is normal (True) or caused by some sort of
        error (False).

        See the notes for connect() (but in reverse) for more details.
        """
        return self._cycle_connstates(disconnect=True, disconnect_ok=ok)

class WebSocketSession(object):
    """
    WebSocketSession(conn, scheduler=None) -> new instance

    A wrapper around a ReconnectingWebSocket providing high-level message
    submission and reception facilities. conn is a ReconnectingWebSocket (or
    an instance of a subclass) providing low-level message handling.
    Theoretically, an entirely different class (using a different underlying
    transport) could be substituted here. scheduler is a Scheduler instance
    that event handlers are executed in.

    Messages sent into the WebSocket are called "commands" and are represented
    by the nested Command class; messages received from the WebSocket are
    called "events" (regardless of their relation to previous commands) and
    are represented by the Event class.

    Read-only instance attributes are:
    conn     : The connection wrapped by this WebSocketSession, as passed to
               the constructor.
    scheduler: The Scheduler responsible for running high-level callbacks.
    commands : An ordered mapping from ID-s to Command instances representing
               still-live commands.
    """

    class Command(object):
        """
        Command(data, id=None, responses=0) -> new instance

        A message sent from a WebSocketSession. data is the payload of the
        command; id is an identifier of the command (for recognizing
        responses); responses is the amount of responses the command expects.

        Instance attributes (all initialized from the corresponding
        constructor parameters, if those exist) are:
        data     : The payload of the command as an arbitrary
                   application-specific object. See also the serialize()
                   method.
        id       : A unique identifier of the command as some hashable object.
                   The value None is special-cased to mean that this command
                   cannot be identified (and, thus, cannot receive responses).
        responses: The amount of responses this command has yet to receive.
                   WebSocketSession retains commands until their responses
                   attribute drops to zero (in particular, commands
                   initialized with responses=0 are forgotten immediately
                   after submission). None is special-cased to mean
                   arbitrarily many (such a command is never discarded).
        state    : The processing state of this command, as a CST_* constant.
                   Managed by the WebSocketSession owing this command.

        Note that command responses are represented as instances of the Event
        class (as there is only one class for incoming frames and labelling
        frames unrelated to any command as "responses" was deemed worse than
        the current naming scheme).
        """

        def __init__(self, data, id=None, responses=0):
            """
            __init__(data, id=None, responses=0) -> None

            Instance initializer; see the class docstring for details.
            """
            self.data = data
            self.id = id
            self.responses = responses
            self.state = CST_NEW

        def serialize(self):
            """
            serialize() -> str or bytes

            Convert this Command into an application-specific on-the-wire
            format and return that as a Unicode or byte string object.

            The default implementation returns the data attribute unchanged,
            violating the method's contract unless data is already a string
            of an appropriate type.
            """
            return self.data

        def on_sending(self):
            """
            on_sending() -> None

            Event handler method invoked when the command has started being
            sent.

            Executed on the scheduler thread; in particular, some bits of the
            command may have already left the process; however, this is
            guaranteed to be scheduled before any related on_response()
            (unless the server guesses the command's ID). The default
            implementation does nothing.
            """
            pass

        def on_sent(self):
            """
            on_sent() -> None

            Event handler method invoked when the command has been
            successfully sent.

            Note that a server might respond to the command before it has been
            fully received (or transmitted); in particular, on_response()
            might be invoked before this method (see also on_sending()).

            Executed on the scheduler thread. The default implementation does
            nothing.
            """
            pass

        def on_response(self, evt):
            """
            on_response(evt) -> None

            Event handler method invoked when an event with the same ID as
            this command (i.e. a response to this command) arrives.

            Executed on the scheduler thread. The default implementation does
            nothing.
            """
            pass

    class Event(object):
        """
        Event(data, connid, id=None) -> new instance

        A message received from the underlying connection of a
        WebSocketSession. data is the payload of the event; id is an
        identifier for matching events to related commands.

        Instance attributes (all initialized from the corresponding
        constructor parameters) are:
        data  : The payload of the event as an arbitrary application-specific
                object. See also the deserialize() method.
        connid: The ID of the connection the event received from.
        id    : An identifier relating this event to some command. None is
                special-cased to mean that this event cannot be identified.
                See also the Command class for more details on reply matching.
        """

        @classmethod
        def deserialize(cls, data, connid):
            """
            deserialize(data, connid) -> new instance

            Convert the given data from an application-specific on-the-wire
            format into an internal format.

            The default implementation returns an instance with data
            unchanged, connid passed on, and an id of None.
            """
            return cls(data, connid)

        def __init__(self, data, connid, id=None):
            """
            __init__(data, connid, id=None) -> None

            Instance initializer; see the class docstring for details.
            """
            self.data = data
            self.connid = connid
            self.id = id

    @classmethod
    def create(cls, url, protos=None, **kwds):
        """
        create(url, protos=None, conn_cls=None, **kwds) -> new instance

        Create a new WebSocketSession along with a new enclosed
        ReconnectingWebSocket. url and protos are forwarded to the
        ReconnectingWebSocket constructor; other keyword arguments are
        forwarded to the WebSocketSession constructor.
        """
        conn_cls = kwds.pop('conn_cls', None)
        if conn_cls is None: conn_cls = ReconnectingWebSocket
        return cls(conn_cls(url, protos), **kwds)

    def __init__(self, conn, scheduler=None):
        """
        __init__(conn, scheduler=None) -> None

        Instance initializer; see the class docstring for details.
        """
        if scheduler is None: scheduler = Scheduler()
        self.conn = conn
        self.scheduler = scheduler
        self.commands = collections.OrderedDict()
        self._lock = threading.RLock()
        self._install_callbacks()

    def __enter__(self):
        "Context manager entry; internal."
        self._lock.__enter__()

    def __exit__(self, *args):
        "Context manager exit; internal."
        self._lock.__exit__(*args)

    def _install_callbacks(self):
        """
        _install_callbacks() -> None

        Wire up callbacks for interesting events into this instance's
        connection and scheduler.
        """
        self.conn.message_cb = self.scheduler.wrap(self._on_raw_message)
        self.conn.error_cb = self.on_error
        self.scheduler.on_error = lambda exc: self.on_error(
            exc, ERRS_SCHEDULER, True)

    def _on_command_sending(self, cmd):
        """
        _on_command_sending(cmd) -> None

        Event handler method invoked when the given command is about to be
        sent. Executed synchronously just before the actual send.

        The default implementation updates the command's state and schedules
        its on_sending() method to be run.
        """
        with self:
            if cmd.state == CST_NEW:
                cmd.state = CST_SENDING
            self.scheduler.add_now(cmd.on_sending)

    def _on_command_sent(self, cmd):
        """
        _on_command_sent(cmd) -> None

        Event handler method invoked when the given command has been
        successfully sent. Executed synchronously just after the send.

        The default implementation updates the command's state and schedules
        its on_sent() method to be run.
        """
        with self:
            if cmd.state in (CST_NEW, CST_SENDING):
                cmd.state = CST_SENT
            self.scheduler.add_now(cmd.on_sent)

    def _on_raw_message(self, msg, connid):
        """
        _on_raw_message(msg, connid) -> None

        Event handler method invoked when a message is received.

        Executed on the scheduler thread. This implementation constructs an
        Event from msg, dispatches it to either a command with the same ID
        (see Command.on_response()) or this instance's on_event() (if there is
        no such command), and garbage-collects the dispatched-to command (if
        any and as necessary).
        """
        evt = self.Event.deserialize(msg, connid)
        with self:
            cmd = self.commands.get(evt.id)
            if cmd is not None and cmd.state in (CST_NEW, CST_SENDING,
                                                 CST_SENT):
                cmd.state = CST_CONFIRMED
        if cmd is not None:
            cmd.on_response(evt)
        else:
            self.on_event(evt)
        with self:
            if cmd is not None and cmd.responses is not None:
                cmd.responses -= 1
                if cmd.responses <= 0:
                    self.commands.pop(evt.id, None)

    def on_event(self, evt):
        """
        on_event(evt) -> None

        Event handler method invoked when an Event that does not match any
        known command is received.

        Executed on the scheduler thread. The default implementation does
        nothing.
        """
        pass

    def on_error(self, exc, source, swallow=False):
        """
        on_error(exc, source, swallow=False) -> None

        Event handler method invoked when an error occurs. See
        ReconnectingWebSocket.on_error() for details.
        """
        if not swallow: raise

    def submit(self, cmd):
        """
        submit(cmd) -> Future

        Send the given Command instance into the underlying connection and
        register it as waiting for responses (as necessary).
        """
        with self:
            if cmd.id is not None and (cmd.responses is None or
                                       cmd.responses > 0):
                self.commands[cmd.id] = cmd
            if cmd.state == CST_NEW:
                cmd.state = CST_SENDING
        return self.conn.send_message(cmd.serialize(),
                                      lambda: self._on_command_sending(cmd),
                                      lambda: self._on_command_sent(cmd))

    def connect(self, wait=True, **kwds):
        """
        connect(wait=True, **kwds) -> Future

        Establish an underlying connection. Returns a Future that resolves
        whenever the connection is established. wait indicates whether this
        call should block until that is the case. Additional keyword arguments
        are forwarded to ReconnectingWebSocket.connect(); see there for
        details.
        """
        return run_async(self.conn.connect, wait, **kwds)

    def reconnect(self, wait=True, **kwds):
        """
        reconnect(wait=True, **kwds) -> Future

        Re-establish the underlying connection. See connect() and
        ReconnectingWebSocket.reconnect() for details.
        """
        return run_async(self.conn.reconnect, wait, **kwds)

    def disconnect(self, wait=True, **kwds):
        """
        disconnect(wait=True, **kwds) -> Future

        Close the underlying connection. See connect() and
        ReconnectingWebSocket.disconnect() for details.
        """
        return run_async(self.conn.disconnect, wait, **kwds)
