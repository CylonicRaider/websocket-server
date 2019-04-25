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
           'parse_http_date', 'htmlescape', 'CaseDict', 'FormData']

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
                if not self.activ: return False
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
        self._seq = 0

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
            self._seq += 1
            return self.add_raw(self.Task(self, cb, timestamp, daemon,
                                          self._seq))

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
                if not head.daemon: self._references -= 1
            try:
                head.cb()
            except Exception as exc:
                self.on_error(exc)

    def join(self):
        """
        join() -> None

        Wait until a concurrent invocation of run() finishes.
        """
        with self.cond:
            while self._references > 0:
                self.wait(None)
