# websocket_server -- WebSocket/HTTP server/client library
# https://github.com/CylonicRaider/websocket-server

"""
Various tools and utilities.
"""

import os, re, time
import threading
import calendar
import collections, heapq
import email.utils
import xml.sax.saxutils

from .compat import bytearray, xrange

try: # Py2K
    from urlparse import parse_qsl
except ImportError: # Py3K
    from urllib.parse import parse_qsl

__all__ = ['MONTH_NAMES', 'mask', 'new_mask', 'format_http_date',
           'parse_http_date', 'htmlescape', 'spawn_thread_ex', 'spawn_thread',
           'spawn_daemon_thread', 'CaseDict', 'FormData', 'AtomicSequence',
           'Scheduler', 'Future', 'EOFQueue']

# Liberal recognition of the ISO 8601 date-time format used by cookies.py.
ISO_DATETIME_RE = re.compile(r'^ (\d+) - (\d+) - (\d+) (?:T )?'
    r'(\d+) : (\d+) : (\d+) Z? $'.replace(r' ', r'\s*'))

# The English month names as three-letter abbreviations.
MONTH_NAMES = {1: 'Jan',  2: 'Feb',  3: 'Mar',  4: 'Apr',
               5: 'May',  6: 'Jun',  7: 'Jul',  8: 'Aug',
               9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec'}

def mask(key, data):
    """
    mask(key, data) -> bytearray

    Given a four-byte mask and an arbitrary-length data bytearray, mask /
    unmask the latter.
    May be in-place. Actually is in the current implementation. The result
    is returned in any case.
    """
    for i in xrange(len(data)):
        data[i] ^= key[i % 4]
    return data

def new_mask():
    """
    new_mask() -> bytearray

    Create a new mask value as conformant to the protocol.
    """
    return bytearray(os.urandom(4))

def format_http_date(t):
    """
    format_http_date(t) -> str

    Return a string represententing the given UNIX timestamp suitable for
    inclusion into HTTP headers.
    """
    return email.utils.formatdate(t, usegmt=True)

def parse_http_date(s):
    """
    parse_http_date(s) -> int

    Parse a timestamp as it occurs in HTTP and return the corresponding UNIX
    time.
    """
    fields = email.utils.parsedate(s)
    if fields is None:
        m = ISO_DATETIME_RE.match(s)
        if not m:
            raise ValueError('Unrecognized date-time string: %r' % (s,))
        fields = [int(n, 10) for n in m.groups()] + [0, 0, -1]
    return calendar.timegm(fields)

def htmlescape(s):
    """
    htmlescape(s) -> str

    Escape special characters in s to allow embedding it into HTML text or
    attributes.
    """
    return xml.sax.saxutils.escape(s, {'"': '&quot;', "'": '&#39;'})

def spawn_thread_ex(func, args, kwds, daemon=False, init=None):
    """
    spawn_thread_ex(func, args, kwds, daemon=False, init=None)
        -> threading.Thread

    Create a new thread and start it. The thread's target, arguments, and
    keyword arguments are set to func, args, and kwds, respectively. If daemon
    is true, the thread is daemonic. If init is not false, it is invoked
    (synchronously) with the thread as the only positional argument just
    before starting the thread. The thread object is returned.
    """
    thr = threading.Thread(target=func, args=args, kwargs=kwds)
    thr.setDaemon(daemon)
    if init: init(thr)
    thr.start()
    return thr

def spawn_thread(_func, *_args, **_kwds):
    """
    spawn_thread(func, *args, **kwds) -> threading.Thread

    Create a non-daemonic thread executing func(*args, **kwds), start it,
    and return it.
    """
    return spawn_thread_ex(_func, _args, _kwds)

def spawn_daemon_thread(_func, *_args, **_kwds):
    """
    spawn_daemon_thread(func, *args, **kwds) -> threading.Thread

    Create a daemonic thread executing func(*args, **kwds), start it, and
    return it.
    """
    return spawn_thread_ex(_func, _args, _kwds, daemon=True)

class CaseDict(collections.MutableMapping):
    """
    CaseDict(source=(), **update) -> new instance

    A mapping with case-insensitive (string) keys (the class name is
    abbreviated from CaseInsensitiveDict). See the dict constructor for
    the meanings of the arguments.
    """

    def __init__(_self, _source=(), **_update):
        """
        __init__(source=(), **update) -> None

        See class docstring for details.
        """
        super(CaseDict, _self).__init__() # Using super() to appease pylint.
        _self._data = dict(_source, **_update)
        _self._keys = dict((k.lower(), k) for k in _self._data)

    def __repr__(self):
        """
        repr(self) -> str

        Return a programmer-friendly string representation of self.
        """
        return '%s(%r)' % (self.__class__.__name__, self._data)

    def __iter__(self):
        """
        iter(self) -> iter

        Return an iterator over self.
        """
        return iter(self._data)

    def __len__(self):
        """
        len(self) -> int

        Return the length of self.
        """
        return len(self._data)

    def __contains__(self, key):
        """
        key in self -> bool

        Check whether the given key is contained in self.
        """
        return (key.lower() in self._keys)

    def __getitem__(self, key):
        """
        self[key] -> value

        Return the value associated with the given key.
        """
        return self._data[self._keys[key.lower()]]

    def __setitem__(self, key, value):
        """
        self[key] = value

        Assign the given value to the given key.
        """
        self._data[self._keys.setdefault(key.lower(), key)] = value

    def __delitem__(self, key):
        """
        del self[key]

        Remove the given key from self.
        """
        lower_key = key.lower()
        del self._data[self._keys[lower_key]]
        del self._keys[lower_key]

class FormData(object):
    """
    FormData(pairs=()) -> new instance

    A read-only mapping-like representation of a set of key-value pairs with
    potentially non-unique keys. Intended for convenient retrieval of data
    from HTML form data or query strings.

    pairs is an iterable of (key, value) pairs. The relative order of values
    (per key) is preserved, as is the order of keys (by first appearance).

    The subscript operator (x[y]) and the get() method are geared towards the
    simultaneous retrieval of multiple keys, and return a single value if
    applied to a single key, or a list of values when applied to multiple
    keys. See their docstrings (and get_ex()) for more details.
    """

    @classmethod
    def from_qs(cls, qs, **kwds):
        """
        from_qs(qs, **kwds) -> new instance

        Parse a query string and convert the result into a FormData instance.
        Keyword arguments are forwarded to the parse_qsl() function.
        """
        return cls(parse_qsl(qs, **kwds))

    @classmethod
    def from_dict(cls, src):
        """
        from_dict(src) -> new instance

        Convert a mapping where each key is mapped to an iterable of values
        to a corresponding FormData instance.
        """
        def make_pairs():
            for k, v in src.items():
                for e in v:
                    yield (k, e)
        return cls(make_pairs())

    def __init__(self, pairs=()):
        """
        __init__(pairs=()) -> None

        Instance initializer; see the class docstring for details.
        """
        self.data = collections.OrderedDict()
        for k, v in pairs:
            self.data.setdefault(k, []).append(v)

    def __bool__(self):
        """
        bool(self) -> bool

        Return whether this instance is nonempty.
        """
        return bool(self.data)

    def __nonzero__(self):
        """
        bool(self) -> bool

        Return whether this instance is nonempty.
        """
        return bool(self.data)

    def __getitem__(self, key):
        """
        self[key] -> value

        This is equivalent to self.get_ex(key), or self.get_ex(*key) if
        key is a tuple or a list.
        """
        if isinstance(key, (tuple, list)):
            return self.get_ex(*key)
        else:
            return self.get_ex(key)

    def keys(self):
        """
        keys() -> keys

        Return the keys of this mapping. Note that attempting to subscript
        this instance with each key may still fail (if there are multiple
        values for it); use get_all() to retrieve all values corresponding
        to a key reliably.
        """
        return self.data.keys()

    def get_all(self, key, **kwds):
        """
        get_all(key, [default]) -> list

        Return all values corresponding to key, or default if given, or raise
        a KeyError.
        """
        try:
            return self.data[key]
        except KeyError:
            try:
                return kwds['default']
            except KeyError:
                raise KeyError(key)

    def get_ex(self, *keys, **kwds):
        """
        get_ex(*keys, [default], first=False, list=False) -> list or str

        Retrieve values corresponding to keys. If default is not omitted,
        it is substituted for keys for which there is *no* value. If first is
        false and there are multiple values for a key, a KeyError is raised;
        otherwise, the first (or only) value for the key is returned. If
        list is false and there is only one key, only the value corresponding
        to it is retrieved; otherwise, a (potentially one-element) list of
        values is returned.
        """
        first, always_list, ret = kwds.get('first'), kwds.get('list'), []
        for k in keys:
            v = self.data.get(k, ())
            if not v:
                try:
                    ret.append(kwds['default'])
                except KeyError:
                    raise KeyError('No value for %r' % (k,))
            elif len(v) > 1 and not first:
                raise KeyError('Too many values for %r' % (k,))
            else:
                ret.append(v[0])
        if len(ret) == 1 and not always_list: ret = ret[0]
        return ret

    def get(self, *keys, **kwds):
        """
        get(*keys, default=None, first=False, list=False) -> list or str

        Retrieve values corresponding to keys, substituting default where
        there is no value corresponding to a key. Note that here, default is
        always defined (and itself defaults to None).
        """
        kwds.setdefault('default', None)
        return self.get_ex(*keys, **kwds)

    def items(self):
        """
        items() -> iterator

        Iterate over all items in self in approximate insertion order.
        """
        for k, v in self.data.items():
            for e in v:
                yield (k, e)

class AtomicSequence(object):
    """
    AtomicSequence(start=0, lock=None) -> new instance

    A thread-safe counter. Each time an instance is called it returns the
    current value of an internal counter (which is initialized with start) and
    increments the counter. lock specifies the lock to synchonize on; if None
    is passed, a new lock is created internally.
    """

    def __init__(self, start=0, lock=None):
        """
        __init__(start=0, lock=None) -> None

        Instance initializer; see the class docstring for details.
        """
        if lock is None: lock = threading.RLock()
        self.counter = start
        self.lock = lock

    def __call__(self):
        """
        __call__() -> int

        Increment the internal counter and return its value *before* the
        increment.

        The return value is declared as "int"; specifying a different starting
        value in the constructor may result in a different return type (as
        long as one can meaningfully add 1 to instances of the type).
        """
        with self.lock:
            ret = self.counter
            self.counter += 1
            return ret

class Future(object):
    """
    Future(cb=None, lock=None) -> new instance

    A wrapper around an object that may have yet to be computed. The
    computation of the object is either represented by the callable cb, which
    is called with no arguments and returns the computed object; or happens
    outside this Future with the result assigned via the set() method (if cb
    is None). lock, if not None, specifies the lock to synchronize internal
    operations on (defaulting to a new lock of an appropriate type).

    Read-only instance attributes are:
    cb       : The callback producing this Future's value (if any).
    value    : The object enclosed by this Future, or None if it has not been
               computed (yet).
    error    : The exception object this Future failed with, or None if that
               has not happened (yet).
    state    : The computation state of this Future (one of the ST_PENDING ->
               ST_COMPUTING -> ST_DONE or ST_FAILED constants). Note that the
               value might change immediately after being accessed.
    error_cbs: A list of callbacks to be run when the callback of this Future
               (if any) raises an exception. If so, the Future's state is set
               to ST_FAILED (waking any concurrent wait() calls), the error
               callbacks are run, and the Future resolves (regularly) to a
               value of None (invoking all done callbacks). See also
               add_error_cb().
    done_cbs : A list of callbacks to be run whenever this Future resolves.
               Each is given the value resolved to as the only positional
               argument. See also add_done_cb().
    """

    ST_PENDING   = 'PENDING'
    ST_COMPUTING = 'COMPUTING'
    ST_FAILED    = 'FAILED'
    ST_DONE      = 'DONE'

    class Timeout(Exception):
        """
        An exception indicating that a timed wait for a Future did not
        succeed.
        """

    @classmethod
    def resolved(cls, value=None):
        """
        resolved(value=None) -> new instance

        Return a Future that is already resolved to the given value.
        """
        ret = cls()
        ret.set(value)
        return ret

    def __init__(self, cb=None, lock=None):
        """
        __init__(cb=None, lock=None) -> None

        Instance initializer; see the class docstring for details.
        """
        self.cb = cb
        self.value = None
        self.error = None
        self.state = self.ST_PENDING
        self.error_cbs = []
        self.done_cbs = []
        self._cond = threading.Condition(lock)

    def _set(self, value, check_state, set_state):
        """
        _set(value, check_state, set_state) -> bool

        Internal: Test whether the state matches check_state; if it does, set
        the state to set_state, the instance's value to the given value, and
        run on-done callbacks. Returns whether the assignment succeeded (i.e.
        the state matched).
        """
        with self._cond:
            if self.state != check_state: return False
            self.value = value
            self.state = set_state
            callbacks = tuple(self.done_cbs)
            self.done_cbs = None
            self.error_cbs = None
            self._cond.notifyAll()
        for cb in callbacks:
            cb(value)
        return True

    def _fail(self, exc, check_state):
        """
        _fail(exc, check_state) -> bool

        Internal: Test whether the state matches check_state; if it does, set
        the state to ST_FAILED, the instance's stored error to the given
        value, invoke on-error callbacks, and resolve this instance to a
        value of None. Returns whether the operation succeeded (i.e. if the
        state matched).
        """
        with self._cond:
            if self.state != check_state: return False
            self.error = exc
            self.state = self.ST_FAILED
            callbacks = tuple(self.error_cbs)
            self.error_cbs = None
            self._cond.notifyAll()
        for cb in callbacks:
            cb(exc)
        if not self._set(None, self.ST_FAILED, self.ST_FAILED):
            raise AssertionError('Future experienced an invalid state '
                'transition')
        return True

    def set(self, value=None):
        """
        set(value=None) -> bool

        Explicitly store an object in this Future. value is the value to
        store. Returns whether setting the Future's value succeeded (i.e.
        whether the value was not already there and there was no computation
        of the it running concurrently).

        If value is omitted, this still wakes up all threads waiting for some
        value to be computed; this allows using Future as a one-shot
        equivalent of the threading.Event class.
        """
        return self._set(value, self.ST_PENDING, self.ST_DONE)

    def run(self):
        """
        run() -> bool or Ellipsis

        Compute the value wrapped by this Future if possible. Returns True
        when the computation has finished, or the (truthy) Ellipsis if the
        computation is going on concurrently, or False if there is no stored
        callback to run.
        """
        with self._cond:
            if self.state in (self.ST_DONE, self.ST_FAILED):
                return True
            elif self.state == self.ST_COMPUTING:
                return Ellipsis
            elif self.cb is None:
                return False
            self.state = self.ST_COMPUTING
        try:
            v = self.cb()
        except Exception as exc:
            if not self._fail(exc, self.ST_COMPUTING):
                raise AssertionError('Future has gotten into an invalid '
                    'state')
        else:
            if not self._set(v, self.ST_COMPUTING, self.ST_DONE):
                raise AssertionError('Future has gotten into an invalid '
                    'state')
        return True

    def cancel(self):
        """
        cancel() -> bool

        Cancel this Future's computation if it has not started yet. Returns
        whether cancelling succeeded (i.e. whether the value has neither
        started being computed nor has been explicitly set).

        This is treated as if computing the value failed with an exception but
        that exception turned out to be None.
        """
        return self._fail(None, self.ST_PENDING)

    def get_state(self):
        """
        get_state() -> ST_*

        Retrieve the state of this Future. This has the benefit over reading
        the state attribute directly of synchronizing on the underlying lock
        and thus avoiding reporting inconsistent transient states.
        """
        with self._cond:
            return self.state

    def get(self, default=None):
        """
        get(default=None) -> object

        Retrieve the object wrapped by this Future, or default if the object
        is not available yet or resolving the Future has failed.
        """
        with self._cond:
            return self.value if self.state == self.ST_DONE else default

    def wait(self, timeout=None, run=False, default=None):
        """
        wait(timeout=None, run=False, default=None) -> object

        Wait for the object of this Future to be computed and return it. If
        timeout is not None, it imposes a maximum time to wait for the value
        (in potentially fractional seconds); if the value is not available
        when the timeout expires, a Timeout exception is raised. If run is
        true, this computes the value (in this thread) unless that is already
        happening elsewhere; if there is no stored callback, run is ignored.
        default specifies the value to return if the callback resolving the
        Future failed with an exception.

        It is an error to specify a non-None timeout and run=True; this class
        cannot guarantee that the computation will honor the timeout.
        """
        def get_value():
            return self.value if self.state == self.ST_DONE else default
        with self._cond:
            if self.state in (self.ST_DONE, self.ST_FAILED):
                return get_value()
            elif not run or self.cb is None:
                if timeout is None:
                    while self.state not in (self.ST_DONE, self.ST_FAILED):
                        self._cond.wait()
                    return get_value()
                deadline = time.time() + timeout
                while self.state not in (self.ST_DONE, self.ST_FAILED):
                    now = time.time()
                    if now >= deadline:
                        raise self.Timeout('Future value did not arrive in '
                                           'time')
                    self._cond.wait(deadline - now)
                return get_value()
        if timeout is not None:
            raise ValueError('Cannot honor timeout while computing value')
        self.run()
        with self._cond:
            while self.state not in (self.ST_DONE, self.ST_FAILED):
                self._cond.wait()
            return get_value()

    def add_error_cb(self, cb):
        """
        add_error_cb(cb) -> bool or Ellipsis

        Schedule cb to be invoked if an error happens while computing this
        Future's value. The callback is not invoked if the Future resolves
        without error. cb is passed the exception that the Future failed with.
        This method returns whether the callback has *not* been invoked; a
        return value of Ellipsis indicates that the callback has been
        discarded because the Future already resolved successfully.
        """
        with self._cond:
            if self.state == self.ST_DONE:
                return Ellipsis
            elif self.state != self.ST_FAILED:
                self.error_cbs.append(cb)
                return True
            e = self.error
        cb(e)
        return False

    def add_done_cb(self, cb):
        """
        add_done_cb(cb) -> bool

        Schedule cb to be invoked whenever this Future resolves (or
        immediately if it already did). cb is passed the value the Future
        resolved to as the only argument; its return value is ignored. This
        method returns whether the callback has *not* been invoked but stored
        for later use (for symmetry with add_error_cb()).
        """
        with self._cond:
            if self.state not in (self.ST_DONE, self.ST_FAILED):
                self.done_cbs.append(cb)
                return True
            v = self.value
        cb(v)
        return False

class Scheduler(object):
    """
    Scheduler() -> new instance

    A Scheduler implements potentially delayed execution of tasks (represented
    as Python callables) on a worker thread (with submission from arbitrary
    background threads permitted).

    A Scheduler continues running while there are non-"daemonic" tasks in its
    queue and/or while there are active "holds" on it. Daemonic tasks allow
    executing periodic actions without blocking the Scheduler indefinitely;
    holds allow background threads to ensure the scheduler is running while
    they might submit tasks to it.

    Exceptions (deriving from the Exception class) raised in tasks are caught,
    passed to an optional user-defined error handler, and suppressed. The
    error handler is set via the on_error instance attribute; if not None, it
    is expected to be a callable that accepts a single positional argument
    (the exception being handled) and returns nothing.

    See also the "sched" module in the standard library. A key difference to
    that module's event scheduler is that this Scheduler allows submitting
    tasks while the Scheduler is waiting for the next task to run (without
    additional effort).
    """

    class Task(Future):
        """
        Task(parent, cb, timestamp, daemon, seq) -> new instance

        A concrete task to be executed by a Scheduler. parent is the Scheduler
        this task belongs to; cb is a callable to invoke when executing this
        task; timestamp is the time at which this task is to be executed;
        daemon defines whether this task is "daemonic" (i.e. does not prevent
        the scheduler from stopping); seq is the sequence number of the task
        (used to break ties when tasks are to be executed at exactly the same
        time; the lower seq, the earlier a task runs).

        The constructor parameters are stored as correspondingly-named
        instance attributes; those must not be changed after initialization
        (or erratic behavior occurs).
        """

        def __init__(self, parent, cb, timestamp, daemon, seq):
            """
            __init__(parent, cb, timestamp, daemon, seq) -> None

            Instance initializer; see the class docstring for details.
            """
            Future.__init__(self, cb)
            self.parent = parent
            self.cb = cb
            self.timestamp = timestamp
            self.daemon = daemon
            self.seq = seq
            self._referencing = False
            self._key = (self.timestamp, self.seq)

        def __lt__(self, other): return self._key <  other._key
        def __le__(self, other): return self._key <= other._key
        def __eq__(self, other): return self._key == other._key
        def __ne__(self, other): return self._key != other._key
        def __ge__(self, other): return self._key >= other._key
        def __gt__(self, other): return self._key >  other._key

        def _set(self, *args):
            "Internal method override; see Future for details."
            ret = Future._set(self, *args)
            if ret:
                with self.parent.cond:
                    if self._referencing:
                        self._referencing = False
                        self.parent._references -= 1
                        self.parent.cond.notifyAll()
            return ret

        def _fail(self, exc, *args):
            "Internal method override; see Future for details."
            ret = Future._fail(self, exc, *args)
            self.parent._on_error(exc)
            return ret

    class Hold(object):
        """
        Hold(parent) -> new instance

        An active hold prevents a Scheduler from stopping regardless of
        whether any tasks are pending inside the scheduler. parent is the
        Scheduler the hold is to happen upon.

        The constructor parameter is stored as a same-named instance
        attribute; additionally, the "active" attribute tells whether the
        hold is actually effective.

        Hold instances act as context managers; when used in a with statement,
        the hold is established while the statement's body runs.
        """

        def __init__(self, parent):
            """
            __init__(parent) -> None

            Instance initializer; see the class docstring for details.
            """
            self.parent = parent
            self.active = False

        def __enter__(self):
            "Context manager entry; see the class docstring for details."
            self.acquire()

        def __exit__(self, *args):
            "Context manager exit; see the class docstring for details."
            self.release()

        def acquire(self):
            """
            acquire() -> bool

            Actually establish this hold. Returns whether successful (i.e.
            whether the hold had not been established previously).
            """
            with self.parent.cond:
                if self.active: return False
                self.parent._references += 1
                self.active = True
                return True

        def release(self):
            """
            release() -> bool

            Undo this hold. Returns whether the hold has been successfully
            released.
            """
            with self.parent.cond:
                if not self.active: return False
                self.parent._references -= 1
                self.active = False
                self.parent.cond.notifyAll()
                return True

    def __init__(self):
        """
        __init__() -> None

        Instance initializer; see the class docstring for details.
        """
        self.queue = []
        self.cond = threading.Condition()
        self.on_error = None
        self._references = 0
        self._seq = AtomicSequence(lock=self.cond)

    def time(self):
        """
        time() -> float

        Return the current time. The default implementation returns the
        current UNIX time.
        """
        return time.time()

    def wait(self, delay):
        """
        wait(delay) -> None

        Sleep for the given amount of time. delay is either a floating-point
        number denoting the amount of time to wait or None to wait forever
        (until interrupted externally).
        """
        with self.cond:
            self.cond.wait(delay)

    def clear(self):
        """
        clear() -> None

        Abort all pending tasks. Unless the scheduler is being held, this
        stops concurrent run()s and wakes concurrent join()s.
        """
        with self.cond:
            for task in self.queue:
                task.cancel()

    def add_raw(self, task):
        """
        add_raw(task) -> Task

        Schedule the given task to be run and return it.
        """
        if task.get_state() != Future.ST_PENDING: return
        with self.cond:
            heapq.heappush(self.queue, task)
            if not task.daemon:
                task._referencing = True
                self._references += 1
            self.cond.notifyAll()
        return task

    def add_abs(self, cb, timestamp, daemon=False):
        """
        add_abs(cb, timestamp, daemon=False) -> Task

        Schedule cb to be executed at timestamp. daemon specifies whether the
        task is daemonic (see the Task class for details). Returns a new Task
        object, which can be used to cancel execution again.
        """
        with self.cond:
            return self.add_raw(self.Task(self, cb, timestamp, daemon,
                                          self._seq()))

    def add(self, cb, timediff, daemon=False):
        """
        add(cb, timediff, daemon=False) -> Task

        Schedule cb to be executed in timediff seconds. daemon specifies
        whether the task is daemonic (see the Task class for details). Returns
        a new Task object, which can be used to cancel execution again.
        """
        return self.add_abs(cb, self.time() + timediff, daemon)

    def add_now(self, cb, daemon=False):
        """
        add_now(cb, daemon=False) -> Task

        Schedule cb to be executed as soon as possible. daemon specifies
        whether the resulting task is daemonic (see the Task class for
        details). Returns a new Task object, which can be used to cancel
        execution again (should one have a chance before the task starts
        running).
        """
        return self.add_abs(cb, self.time(), daemon)

    def wrap(self, func):
        """
        wrap(func) -> callable

        Wrap func in a callable that runs func inside this scheduler. When the
        returned callable is invoked, it uses add_now() to schedule a task
        which will run func with any arguments provided to the returned
        callable. The callable's return value is a Task (and thus Future)
        object that allows waiting for the result of the execution or
        cancelling it again (as long as the caller is aware of that).
        """
        # Give the function a fancy name.
        def scheduler_wrapper(*_args, **_kwds):
            return self.add_now(lambda: func(*_args, **_kwds))
        return scheduler_wrapper

    def _on_error(self, exc):
        """
        _on_error(exc) -> None

        Handle an error that occurred while executing a task's callback. exc
        is the Exception instance pertaining to the error; sys.exc_info() may
        be consulted as well.

        The default implementation invokes the on_error instance attribute
        unless that is None.
        """
        handler = self.on_error
        if handler is not None: handler(exc)

    def run(self):
        """
        run() -> None

        Run until no non-daemonic tasks and no holds on this scheduler are
        left.
        """
        while 1:
            with self.cond:
                now = self.time()
                while self._references > 0 and (not self.queue or
                        self.queue[0].timestamp > now):
                    if self.queue:
                        self.wait(self.queue[0].timestamp - now)
                    else:
                        self.wait(None)
                    now = self.time()
                if self._references <= 0: break
                head = heapq.heappop(self.queue)
                if head.cancelled: continue
                head.started = True
            head.run()

    def start(self, daemon=True):
        """
        start(daemon=True) -> threading.Thread

        Start a background thread run()ning this Scheduler. daemon specifies
        whether the thread is daemonic. The thread object is returned.
        """
        return (spawn_daemon_thread if daemon else spawn_thread)(self.run)

    def join(self):
        """
        join() -> None

        Wait until a concurrent invocation of run() finishes.
        """
        with self.cond:
            while self._references > 0:
                self.wait(None)

class EOFQueue(object):
    """
    EOFQueue() -> new instance

    A thread-safe unbounded queue that represents a finite stream of elements.
    The end of the stream is indicated by the producer calling the close()
    method; after that, any elements stored in the queue can be retrieved
    normally, whereafter get() raises an EOFError (an exception is used since
    any value can be legitimately stored in the queue). After calling close(),
    adding new elements is forbidden and raises an EOFError as well.
    """

    def __init__(self):
        """
        __init__() -> None

        Instance initializer; see the class docstring for details.
        """
        self._cond = threading.Condition()
        self._items = collections.deque()
        self._eof = False

    def clear(self):
        """
        clear() -> None

        Remove all items from the queue. This operation always succeeds.
        """
        with self._cond:
            self._items.clear()

    def get(self):
        """
        get() -> object or EOFError

        Return the first item of the queue. If an item is available, it is
        removed from the queue and returned; otherwise, if the queue has been
        close()d, EOFError is raised; otherwise, this blocks until an item
        is put into the queue (or the queue is closed) concurrently.
        """
        with self._cond:
            while not self._items and not self._eof:
                self._cond.wait()
            if self._items:
                return self._items.popleft()
            else:
                raise EOFError('End of EOFQueue reached')

    def put(self, item):
        """
        put(item) -> None

        Append item to the queue, potentially waking a concurrent get(). If
        the queue has been close()d previously, this raises an EOFError.
        """
        with self._cond:
            if self._eof:
                raise EOFError('Attempting to add element to closed EOFQueue')
            self._items.append(item)
            self._cond.notify()

    def close(self):
        """
        close() -> None

        Indicate that no further elements will be added to the queue. If the
        queue is already closed, nothing happens.
        """
        with self._cond:
            self._eof = True
            self._cond.notifyAll()
