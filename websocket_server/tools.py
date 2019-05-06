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
    import thread as _thread
except ImportError: # Py3K
    from urllib.parse import parse_qsl
    import _thread

__all__ = ['MONTH_NAMES', 'mask', 'new_mask', 'format_http_date',
           'parse_http_date', 'htmlescape', 'CaseDict', 'FormData',
           'AtomicSequence', 'Scheduler', 'Future', 'EOFQueue',
           'MutexBarrier']

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

def spawn_thread(_func, *_args, **_kwds):
    """
    spawn_thread(func, *args, **kwds) -> threading.Thread

    Create a non-daemonic thread executing func(*args, **kwds), start it,
    and return it.
    """
    thr = threading.Thread(target=_func, args=_args, kwargs=_kwds)
    thr.start()
    return thr

def spawn_daemon_thread(_func, *_args, **_kwds):
    """
    spawn_daemon_thread(func, *args, **kwds) -> threading.Thread

    Create a daemonic thread executing func(*args, **kwds), start it, and
    return it.
    """
    thr = threading.Thread(target=_func, args=_args, kwargs=_kwds)
    thr.setDaemon(True)
    thr.start()
    return thr

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
        super(CaseDict, _self).__init__()
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

class Scheduler(object):
    """
    Scheduler() -> new instance

    An enhanced variant of the standard library's sched module. This allows
    other threads to submit tasks while the scheduler is waiting for the next
    task and have the submitted tasks execute at the correct time. Scheduled
    tasks can be "daemonic" (a scheduler continues running while there are
    non-daemonic tasks), and the scheduler can be "held" by other threads,
    preventing it from shutting down while they might submit tasks.
    """

    class Task(object):
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
        (or erratic behavior occurs). Additionally, there is a (read-only)
        "cancelled" attribute that tells whether the task has been cancelled,
        and a "started" attribute that tells whether the task has already
        started running.
        """

        def __init__(self, parent, cb, timestamp, daemon, seq):
            """
            __init__(parent, cb, timestamp, daemon, seq) -> None

            Instance initializer; see the class docstring for details.
            """
            self.parent = parent
            self.cb = cb
            self.timestamp = timestamp
            self.daemon = daemon
            self.seq = seq
            self.cancelled = False
            self.started = False
            self._key = (self.timestamp, self.seq)

        def __lt__(self, other): return self._key <  other._key
        def __le__(self, other): return self._key <= other._key
        def __eq__(self, other): return self._key == other._key
        def __ne__(self, other): return self._key != other._key
        def __ge__(self, other): return self._key >= other._key
        def __gt__(self, other): return self._key >  other._key

        def cancel(self):
            """
            cancel() -> bool

            Cancel this task. Returns whether cancelling succeeded.
            """
            with self.parent.cond:
                if not (self.daemon or self.cancelled or self.started):
                    self.parent._pending -= 1
                ok = (not self.cancelled and not self.started)
                self.cancelled = True
                self.parent.cond.notifyAll()
            return ok

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
        with self.cond:
            if task.cancelled: return
            heapq.heappush(self.queue, task)
            if not task.daemon: self._references += 1
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

    def on_error(self, exc):
        """
        on_error(exc) -> None

        Handle an error that occurred while executing a task's callback. exc
        is the Exception instance pertaining to the error; sys.exc_info() may
        be consulted as well.

        The default implementation immediately re-raises exc.
        """
        raise exc

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
            try:
                head.cb()
            except Exception as exc:
                self.on_error(exc)
            finally:
                if not head.daemon:
                    with self.cond:
                        self._references -= 1
                        self.cond.notifyAll()

    def join(self):
        """
        join() -> None

        Wait until a concurrent invocation of run() finishes.
        """
        with self.cond:
            while self._references > 0:
                self.wait(None)

class Future(object):
    """
    Future(cb) -> new instance

    A wrapper around an object that may have yet to be computed. The
    computation of the object is represented by the callable cb, which is
    called with no arguments and returns the computed object.

    Additional read-only instance attributes are:
    value: The object enclosed by this Future, or None is not computed yet.
    state: The computation state of this Future (one of the ST_PENDING ->
           ST_COMPUTING -> ST_DONE constants). Note that reading this is
           probably of little use since the value might change immediately
           after accessing it.
    """

    ST_PENDING   = 'PENDING'
    ST_COMPUTING = 'COMPUTING'
    ST_DONE      = 'DONE'

    class Timeout(Exception):
        """
        An exception indicating that a timed wait for a Future did not
        succeed.
        """

    def __init__(self, cb):
        """
        __init__(cb) -> None

        Instance initializer; see the class docstring for details.
        """
        self.cb = cb
        self.value = None
        self.state = self.ST_PENDING
        self._cond = threading.Condition()

    def run(self):
        """
        run() -> None

        Compute the value wrapped by this Future (if that has not happened
        yet).
        """
        with self._cond:
            if self._state != self.ST_PENDING: return
            self._state = self.ST_COMPUTING
        self.value = self.cb()
        with self._cond:
            self._state = self.ST_DONE
            self._cond.notifyAll()

    def get(self, default=None):
        """
        get(default=None) -> object

        Retrieve the object wrapped by this Future, or default if the object
        is not available yet.
        """
        with self._cond:
            return self.value if self._state == self.ST_DONE else default

    def wait(self, timeout=None, run=False):
        """
        wait(timeout=None, run=False) -> object

        Wait for the object of this Future to be computed and return it. If
        timeout is not None, it imposes a maximum time to wait for the value
        (in potentially fractional seconds); if the value is not available
        when the timeout expires, a Timeout exception is raised. If run is
        true, this computes the value (in this thread) unless that is already
        happening elsewhere. It is an error to specify a non-None timeout and
        run=True; this class cannot guarantee that the computation will honor
        the timeout.
        """
        with self._cond:
            if self._state == self.ST_DONE:
                return self.value
            elif not run:
                if timeout is None:
                    while self._state != self.ST_DONE:
                        self._cond.wait()
                    return self.value
                deadline = time.time() + timeout
                while self._state != self.ST_DONE:
                    now = time.time()
                    if now >= deadline:
                        raise self.Timeout('Future value did not arrive in '
                                           'time')
                    self._cond.wait(deadline - now)
                return self.value
        if timeout is not None:
            raise ValueError('Cannot honor timeout while computing value')
        self.run()
        with self._cond:
            while self._state != self.ST_DONE:
                self._cond.wait()
            return self.value

class MutexBarrier(object):
    """
    MutexBarrier() -> new instance

    A specialized synchronization primitive. A MutexBarrier allows multiple
    threads to participate in a process somewhat similar to an academic
    seminar:
    - First (and optionally), one thread does some sort of work, the
      "presentation";
    - then, all threads participating in the MutexBarrier are executed,
      allowing them to "evaluate" the results of the first thread's work;
    - after that, the cycle repeats.
    A barrier is realized each "second" step to ensure that every
    participating thread had a chance to "evaluate" the results of the first
    step. Membership in a MutexBarrier is dynamic (threads may join and leave
    at any time) and non-reentrant (trying to join while already joined causes
    an exception).

    The join() and leave() methods control membership in a MutexBarrier; the
    check() method implements selection of the "presenter" thread, delaying
    the other threads while the presenter is running, and realizing the
    inter-step barrier; the done() method marks the end of the "presentation"
    and must be invoked if check() returned a true value.

    MutexBarrier implements the context manager protocol; when an instance is
    used in a with statement, the current thread is added to the MutexBarrier
    while the nested code block is executed.

    The intended use pattern of this class is as follows:

        with get_mutexbarrier_somehow() as mb:
            while 1:
                if mb.check():
                    ... # Do work.
                    mb.done()
                ... # Evaluate result of worker, optionally breaking the loop.

    NOTE: As is the case with other synchronization primitives, a MutexBarrier
          may get into an inconsistent state when a member thread terminates
          abruptly (or at all) without leaving the MutexBarrier.
    """

    def __init__(self):
        """
        __init__() -> None

        Instance initializer; see the class docstring for details.
        """
        self._cond = threading.Condition()
        self._members = set()
        self._waiting = None
        self._worker = None

    def __enter__(self):
        "Context manager entry; see the class docstring for details."
        self.join()

    def __exit__(self, *args):
        "Context manager exit; see the class docstring for details."
        self.leave()

    def join(self):
        """
        join() -> None

        Join the MutexBarrier. If this thread has already joined the
        MutexBarrier, an exception is raised.
        """
        with self._cond:
            tid = _thread.get_ident()
            if tid in self._members:
                raise RuntimeError('Joining MutexBarrier although already '
                    'joined')
            self._members.add(tid)

    def check(self, may_work=True):
        """
        check(may_work=True) -> bool

        Main operation. may_work specifies whether this thread may be chosen
        as the "presenter".

        - First, this waits until all other member threads have entered this
          method as well (or left the MutexBarrier);
        - then one "presenter" thread is selected among those that specified
          may_work as true; the exact way of selection is not specified;
        - the presenter thread's call is finished with a return value of True;
        - the other threads wait until done() is called (or the worker thread
          leaves);
        - finally, the other threads' calls return False.
        """
        with self._cond:
            # Check for misuse.
            tid = _thread.get_ident()
            if tid == self._worker:
                raise RuntimeError('Did not call MutexBarrier.done() '
                    'although given true return value from check()')
            # Register as the worker if no other thread has done so.
            is_worker = (may_work and self._worker is None)
            if is_worker:
                self._worker = tid
            # Wait until every other thread reaches the (virtual) barrier.
            self._waiting += 1
            while self._waiting < len(self._members):
                self._cond.wait()
            self._waiting -= 1
            # Return early if we are the worker.
            if is_worker:
                return True
            # Otherwise, wait until the worker is done and return False.
            while self._worker is not None:
                self._cond.wait()
            return False

    def done(self):
        """
        done() -> None

        Notify the other threads that the "presentation phrase" is done. If
        this is called by a thread other than the designated "presenter", an
        exception is raised.
        """
        with self._cond:
            tid = _thread.get_ident()
            if tid != self._worker:
                raise RuntimeError('Calling MutexBarrier.done() although not '
                    'designated')
            self._worker = None
            self._cond.notifyAll()

    def leave(self):
        """
        leave() -> None

        Leave the MutexBarrier. If this thread has not a member of the
        MutexBarrier, an exception is raised.
        """
        with self._cond:
            tid = _thread.get_ident()
            if tid not in self._members:
                raise RuntimeError('Leaving MutexBarrier without joining')
            wake = False
            if tid == self._worker:
                self._worker = None
                wake = True
            self._members.remove(tid)
            if wake or self._waiting == len(self._members):
                self._cond.notifyAll()

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
