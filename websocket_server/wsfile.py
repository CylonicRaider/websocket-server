# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
WebSocket protocol implementation.

See the WebSocketFile class for more information.
"""

import struct
import codecs
import threading
from collections import namedtuple

from . import constants
from .compat import bytearray, bytes, unicode
from .exceptions import *
from .tools import mask, new_mask

__all__ = ['WebSocketFile', 'wrap']

# Allocation unit.
BUFFER_SIZE = 16384

# Frame class
Frame = namedtuple('Frame', ('opcode', 'payload', 'final', 'msgtype'))

# Message class
Message = namedtuple('Message', ('msgtype', 'content', 'final'))

# Adapted from RFC 6455:
#  0               1               2               3
#  0 1 2 3 4 5 6 7 0 1 2 3 4 5 6 7 0 1 2 3 4 5 6 7 0 1 2 3 4 5 6 7
# +-+-+-+-+-------+-+-------------+-------------------------------+
# |F|R|R|R| opcode|M| Payload len |    Extended payload length    |
# |I|S|S|S|  (4)  |A|     (7)     |             (16/64)           |
# |N|V|V|V|       |S|             |   (if payload len==126/127)   |
# | |1|2|3|       |K|             |                               |
# +-+-+-+-+-------+-+-------------+ - - - - - - - - - - - - - - - +
# |     Extended payload length continued, if payload len == 127  |
# + - - - - - - - - - - - - - - - +-------------------------------+
# |                               |Masking-key, if MASK set to 1  |
# +-------------------------------+-------------------------------+
# | Masking-key (continued)       |          Payload Data         |
# +-------------------------------- - - - - - - - - - - - - - - - +
# :                     Payload Data continued ...                :
# + - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - +
# |                     Payload Data continued ...                |
# +---------------------------------------------------------------+

class WebSocketFile(object):
    """
    WebSocket protocol implementation. May base on a pair of file-like
    objects (for usage in HTTPRequestHandler's); a "raw" socket (if you
    prefer parsing HTTP headers yourself); or a single file object (if
    you've got such a read-write one). This class is *not* concerned
    with the handshake; use other methods (like the built-in HTTP servers
    (or clients)) for performing it.

    WebSocketFile(rdfile, wrfile, server_side=False)
    rdfile     : File to perform reading operations on.
    wrfile     : File to perform writing operations on.
    server_side: Whether to engage server-side behavior (if true) or not
                 (otherwise).

    Attributes:
    server_side  : Whether this is a server-side WebSocketFile
    close_wrapped: Whether calling close() should close the underlying files
                   as well. Defaults to True.
    _rdlock      : threading.RLock instance used for serializing and
                   protecting reading-related operations.
    _wrlock      : threading.RLock instance user for serializing and
                   protecting write-related operations.
                   _rdlock should always be asserted before _wrlock, if at
                   all; generally don't call reading-related methods (which
                   also include close*()) with _wrlock asserted, and don't
                   use those locks unless necessary. Make your own.
    _socket      : Underlying socket (set by the client and server modules).
                   May not be present at all. Only use this if you are really
                   sure you need to.

    Class attributes:
    MAXFRAME    : Maximum frame payload length. May be overridden by
                  subclasses (or instances). Value is either an integer or
                  None (indicating no limit). This is not enforced for
                  outgoing messages.
    MAXCONTFRAME: Maximum length of a frame reconstructed from fragments. May
                  be overridden as well. The value has the same semantics as
                  the one of MAXFRAME. This is not enforced for outgoing
                  messages as well.

    NOTE: This class reads exactly the amount of bytes needed, yet buffering
          of the underlying stream may cause frames to "congest".
          The underlying stream must be blocking, or unpredictable behavior
          occurs.
    """

    # Maximum allowed frame length.
    MAXFRAME = None

    # Maximum continued frame length.
    MAXCONTFRAME = None

    @classmethod
    def from_files(cls, rdfile, wrfile, server_side=False):
        """
        from_files(cls, rdfile, wrfile, server_side=False) -> WebSocketFile

        Equivalent to the constructor; provided for symmetry.
        """
        return cls(rdfile, wrfile, server_side)

    @classmethod
    def from_socket(cls, socket, server_side=False):
        """
        from_socket(cls, socket, server_side=False) -> WebSocketFile

        Wrap a socket in a WebSocketFile. Uses the makefile() method
        to obtain the file objects internall used.
        """
        return cls.from_file(socket.makefile('rwb'), server_side)

    @classmethod
    def from_file(cls, file, server_side=False):
        """
        from_file(cls, file, server_side=False) -> WebSocketFile

        Wrap a read-write file object.
        """
        return cls(file, file, server_side)

    def __init__(self, rdfile, wrfile, server_side=False):
        """
        __init__(rdfile, wrfile, server_side=False) -> None

        See the class docstring for details.
        """
        self._rdfile = rdfile
        self._wrfile = wrfile
        self._socket = None
        self.server_side = server_side
        self.close_wrapped = True
        self._rdlock = threading.RLock()
        self._wrlock = threading.RLock()
        factory = codecs.getincrementaldecoder('utf-8')
        self._decoder = factory(errors='strict')
        self._cur_opcode = None
        self._read_close = False
        self._written_close = False
        self._closed = False

    def _read_raw(self, length):
        """
        _read_raw(length) -> bytes

        Read exactly length bytes from the underlying stream, and return
        them as a bytes object.
        Should be used for small amounts.
        Raises EOFError if less than length bytes are read.
        """
        if not length: return b''
        rf = self._rdfile
        buf, buflen = [], 0
        while buflen < length:
            rd = rf.read(length - buflen)
            if not rd:
                raise EOFError()
            buf.append(rd)
            buflen += len(rd)
        return b''.join(buf)

    def _readinto_raw(self, buf, offset=0):
        """
        _readinto_raw(buf, offset=0) -> buf

        Try to fill buf with exactly as many bytes as buf can hold.
        If buf is an integer, a bytearray object of that length is
        allocated and returned.
        If offset is nonzero, reading starts at that offset.
        Raises EOFError on failure.
        """
        # Convert integers into byte arrays.
        if isinstance(buf, int): buf = bytearray(buf)
        # Don't fail on empty reads.
        if not buf: return buf
        # Main... try-except clause.
        rf, fl = self._rdfile, len(buf)
        try:
            # Try "native" readinto method.
            if not offset:
                l = rf.readinto(buf)
                if l == 0:
                    # EOF
                    raise EOFError()
            else:
                l = offset
            if l < len(buf):
                # Fill the rest.
                try:
                    # Try still to use buf itself (indirectly).
                    v, o = memoryview(buf), l
                    while o < fl:
                        rd = rf.readinto(v[o:])
                        if not rd:
                            raise EOFError()
                        o += rd
                except NameError:
                    # Will have to read individual parts.
                    o = l
                    temp = bytearray(min(fl - o, BUFFER_SIZE))
                    while o < fl:
                        if len(temp) > fl - o:
                            temp = bytearray(fl - o)
                        rd = rf.readinto(temp)
                        if not rd:
                            raise EOFError()
                        no = o + rd
                        buf[o:no] = temp
                        o = no
        except AttributeError:
            # No readinto available, have to read chunks.
            o, fl = offset, len(buf)
            while o < fl:
                chunk = rf.read(min(fl - o, BUFFER_SIZE))
                if not chunk:
                    raise EOFError()
                no = o + len(chunk)
                buf[o:no] = chunk
                o = no
        return buf

    def _write_raw(self, data):
        """
        _write_raw(data) -> None

        Write data to the underlying stream. May or may be not buffered.
        """
        self._wrfile.write(data)

    def _flush_raw(self):
        """
        _flush_raw() -> None

        Force any buffered output data to be written out.
        """
        self._wrfile.flush()

    def read_single_frame(self):
        """
        read_single_frame() -> (opcode, payload, final, type) or None

        Read (and parse) a single WebSocket frame.
        opcode is the opcode of the frame, as an integer; payload is the
        payload of the frame, text data is *not* decoded; final is a
        boolean indicating whether this frame was final, type is the same
        as opcode for non-continuation frames, and the opcode of the frame
        continued for continuation frames. The return value is a named
        tuple, with the fields named as indicated.
        If EOF is reached (not in the middle of the frame), None is
        returned.
        MAXFRAME is applied.
        May raise ProtocolError (via error()) if the data received is
        invalid, is truncated, an invalid (non-)continuation frame
        is read, EOF inside an unfinished fragmented frame is
        encountered, etc.
        """
        with self._rdlock:
            # Store for later.
            was_read_close = self._read_close
            # No more reading after close.
            if was_read_close:
                return None
            # Read opcode byte. A EOF here is non-fatal.
            header = bytearray(2)
            try:
                header[0] = ord(self._read_raw(1))
            except EOFError:
                if self._cur_opcode is not None:
                    self._error('Unfinished fragmented frame')
                return None
            # ...And EOF from here on, on the other hand, is.
            try:
                # Read the length byte.
                header[1] = ord(self._read_raw(1))
                # Extract header fields.
                final = header[0] & constants.FLAG_FIN
                reserved = header[0] & constants.MASK_RSV
                opcode = header[0] & constants.MASK_OPCODE
                masked = header[1] & constants.FLAG_MASK
                length = header[1] & constants.MASK_LENGTH
                # Verify them.
                if reserved:
                    self._error('Frame with reserved flags received')
                if bool(self.server_side) ^ bool(masked):
                    self._error('Frame with invalid masking received')
                if opcode & constants.OPMASK_CONTROL and not final:
                    self._error('Fragmented control frame received')
                # (Fragmented) Message type.
                msgtype = opcode
                # Validate fragmentation state.
                if not opcode & constants.OPMASK_CONTROL:
                    # Control frames may pass freely, non-control ones
                    # interact with the state.
                    if opcode == constants.OP_CONT:
                        # Continuation frame.
                        msgtype = self._cur_opcode
                        if self._cur_opcode is not None:
                            # See the error message.
                            self._error('Orphaned continuation frame')
                        elif final:
                            # Finishing fragmented frame.
                            self._cur_opcode = None
                        # "Normal" continuation frame passed.
                    else:
                        # "Header" frame.
                        if self._cur_opcode is not None:
                            # Already inside fragmented frame.
                            self._error('Fragmented frame interrupted')
                        elif not final:
                            # Fragmented frame started.
                            self._cur_opcode = opcode
                        # Self-contained frame passed -- no action.
                # Extract length and mask value; start reading payload
                # buffer.
                masklen = (4 if masked else 0)
                if length < 126:
                    # Just read the mask if necessary.
                    msk = self._readinto_raw(masklen)
                elif length == 126:
                    buf = self._readinto_raw(2 + masklen)
                    length = struct.unpack('!H', buf[:2])
                    # Validate length
                    if length < 126:
                        self._error('Invalid frame length encoding')
                    if masked: msk = buf[2:6]
                elif length == 127:
                    buf = self._readinto_raw(4 + masklen)
                    length = struct.unpack('!Q', buf[:4])
                    # Validate length.
                    if length < 65536:
                        self._error('Invalid frame length encoding')
                    elif length >= 9223372036854775808: # 2 ** 63
                        # MUST in RFC 6455, section 5.2
                        # We could handle those frames easily (given we have
                        # enough memory), though.
                        self._error('Frame too long')
                    if masked: msk = buf[4:8]
                # Validate length.
                if self.MAXFRAME is not None and length > self.MAXFRAME:
                    self._error('Frame too long',
                                code=constants.CLOSE_MESSAGE_TOO_BIG)
                # Allocate result buffer.
                rbuf = bytearray(length)
                # Read rest of message.
                self._readinto_raw(rbuf)
                # Verify this is not a post-close frame.
                if was_read_close:
                    self._error('Received frame after closing one')
                # Reverse masking if necessary.
                if masked: rbuf = mask(msk, rbuf)
                # Done!
                return Frame(opcode, bytes(rbuf), bool(final), msgtype)
            except EOFError:
                self._error('Truncated frame')

    def read_frame(self, stream=False):
        """
        read_frame(stream=False) -> (msgtype, data, final) or None

        Read a WebSocket data frame.
        The return value is composed from fields of the same meaning
        as from read_single_frame(). Note that the opcode field is
        discarded in favor of msgtype. The return value is (as in
        read_single_frame()), a named tuple, with the field names as
        indicated. If the stream encounters an EOF, returns None.
        If stream is false, fragmented frames are re-combined into a
        single frame (MAXCONTFRAME is applied), otherwise, they are
        returned individually.
        If the beginning of a fragmented frame was already consumed,
        the remainder of it (or one frame of the remainder, depending
        on stream) is read.
        May raise ProtocolError (if read_single_frame() does), or
        InvalidDataError, if decoding a text frame fails.
        NOTE: The data returned may not correspond entirely to the
              payload of the underlying frame, if the latter contains
              incomplete UTF-8 sequences.
        """
        buf, buflen = [], 0
        with self._rdlock:
            while 1:
                # Read frame.
                fr = self.read_single_frame()
                # EOF reached. Assuming state is clean.
                if not fr: return None
                # Process control frames as quickly as possible.
                if fr.opcode & constants.OPMASK_CONTROL:
                    self.handle_control(fr.opcode, fr.payload)
                    continue
                # Decode text frames.
                if fr.opcode == constants.OP_TEXT:
                    try:
                        payload = self._decoder.decode(fr.payload,
                                                       fr.final)
                    except ValueError:
                        raise InvalidDataError('Invalid message payload')
                else:
                    payload = fr.payload
                # Enforce MAXCONTFRAME
                if (self.MAXCONTFRAME is not None and
                        buflen + len(payload) > self.MAXCONTFRAME):
                    self._error('Fragmented frame too long',
                                code=constants.CLOSE_MESSAGE_TOO_BIG)
                # Prepare value for returning.
                datum = Message(fr.msgtype, payload, fr.final)
                # Regard streaming mode.
                if stream:
                    return datum
                # Accumulate non-final frames.
                buf.append(datum.content)
                buflen += len(datum.content)
                # Stop if final message encountered.
                if datum.final:
                    if datum.msgtype == constants.OP_TEXT:
                        base = unicode()
                    else:
                        base = bytes()
                    return Message(datum.msgtype, base.join(buf), True)

    def handle_control(self, opcode, cnt):
        """
        handle_control(opcode, cnt) -> bool

        Handle a control frame.
        Called by read_frame() if a control frame is read, to evoke a
        required response "as soon as practical".
        The return value tells whether it is safe to continue reading (true),
        or if EOF (i.e. a close frame) was reached (false).
        """
        if opcode == constants.OP_PING:
            self.write_single_frame(constants.OP_PONG, cnt)
        elif opcode == constants.OP_CLOSE:
            self._read_close = True
            self.close_ex(*self.parse_close(cnt))
            return False
        return True

    # Used internally.
    def _error(self, message):
        self.error(message)
        # Assure execution does not continue.
        raise RuntimeError('error() did return')

    def error(self, message, code=constants.CLOSE_PROTOCOL_FAILURE):
        """
        error(message, code=CLOSE_PROTOCOL_FAILURE) -> [ProtocolError]

        Initiate an abnormal connection close and raise a ProtocolError.
        code is the error code to use.
        This method is called from read_single_frame() if an invalid
        frame is detected.
        """
        self.close_ex(code, message)
        raise ProtocolError(message, code=code)

    def write_single_frame(self, opcode, data, final=True, maskkey=None):
        """
        write_single_frame(opcode, data, final=True, maskkey=None) -> None

        Write a frame with the given parameters.
        final determines whether the frame is final; opcode is one of the
        OP_* constants; data is the payload of the message. maskkey, if not
        None, is a length-four byte sequence that determines which mask key
        to use, otherwise, tools.new_mask() will be invoked to create one
        if necessary.
        If opcode is OP_TEXT, data may be a Unicode or a byte string,
        otherwise, data must be a byte string. If the type of data is
        inappropriate, TypeError is raised.
        Raises ConnectionClosedError is the connection is already closed or
        closing.
        """
        # Validate arguments.
        if not constants.OP_MIN <= opcode <= constants.OP_MAX:
            raise ValueError('Opcode out of range')
        if isinstance(data, unicode):
            if opcode != constants.OP_TEXT:
                raise TypeError('Unicode payload specfied for '
                    'non-Unicode opcode')
            data = data.encode('utf-8')
        elif not isinstance(data, (bytes, bytearray)):
            raise TypeError('Invalid data type')
        # Allocate new mask if necessary; validate type.
        masked = (not self.server_side)
        if masked:
            if maskkey is None:
                maskkey = new_mask()
            elif isinstance(maskkey, bytes):
                maskkey = bytearray(maskkey)
        else:
            maskkey = None
        # Construct message header.
        header = bytearray(2)
        if final: header[0] |= constants.FLAG_FIN
        if masked: header[1] |= constants.FLAG_MASK
        header[0] |= opcode
        # Insert message length.
        if len(data) < 126:
            header[1] |= len(data)
        elif len(data) < 65536:
            header[1] |= 126
            header.extend(struct.pack('!H', len(data)))
        elif len(data) < 9223372036854775808: # 2 ** 63
            header[1] |= 127
            header.extend(struct.pack('!Q', len(data)))
        else:
            # WTF?
            raise ValueError('Frame too long')
        # Masking.
        if masked:
            # Add key to header.
            header.extend(maskkey)
            # Actually mask data.
            data = mask(maskkey, bytearray(data))
        # Drain all that onto the wire.
        with self._wrlock:
            if self._written_close:
                raise ConnectionClosedError(
                    'Trying to write data after close()')
            self._write_raw(header)
            self._write_raw(data)
            self._flush_raw()

    def write_frame(self, opcode, data):
        """
        write_frame(opcode, data) -> None

        Write a complete data frame with given opcode and data.
        Arguments are validated. May raise exceptions as
        write_single_frame() does.
        """
        if opcode & constants.OPMASK_CONTROL or opcode == constants.OP_CONT:
            raise ValueError('Trying to write non-data frame')
        self.write_single_frame(opcode, data)

    def write_text_frame(self, data):
        """
        write_text_frame(data) -> None

        Write an OP_TEXT frame with given data, which must be a Unicode
        string.
        """
        if not isinstance(data, unicode): raise TypeError('Invalid data')
        return self.write_frame(constants.OP_TEXT, data)

    def write_binary_frame(self, data):
        """
        write_binary_frame(data) -> None

        Write an OP_BINARY frame with given data.
        """
        return self.write_frame(constants.OP_BINARY, data)

    def close_ex(self, code=None, message=None, wait=False):
        """
        close_ex(code=None, message=None, wait=False) -> None

        Close the underlying connection, delivering the code and message (if
        given) to the other point. If code is None, message is ignored. If
        message is a Unicode string, it is encoded using UTF-8. If wait is
        true, this will read frames from self until the other side
        acknowledges the close; as this may cause data loss, be careful.
        If the connection is already closed, the method has no effect.
        """
        # Construct payload.
        payload = bytearray()
        if code is not None:
            # Add code.
            payload.extend(struct.pack('!H', code))
            # Add message.
            if message is None:
                pass
            elif isinstance(message, unicode):
                payload.extend(message.encode('utf-8'))
            else:
                payload.extend(message)
        with self._wrlock:
            # Already closed?
            if self._written_close:
                # Close underlying streams if necessary.
                if (self._read_close and self.close_wrapped and
                        not self._closed):
                    self._rdfile.close()
                    self._wrfile.close()
                    self._closed = True
                # Anyway, won't write another frame.
                return
            # Write close frame.
            self.write_single_frame(constants.OP_CLOSE, payload)
            # Close frame written.
            self._written_close = True
        # Wait for close if desired.
        if wait:
            with self._rdlock:
                while self.read_single_frame(): pass

    def close(self, message=None, wait=False):
        """
        close(message=None, wait=False) -> None

        Close the underlying connection with a code of CLOSE_NORMAL
        and the (optional) given message. If wait is true, this will
        read frames from self until the other side acknowledges the
        close; as this may cause data loss, be careful.
        """
        self.close_ex(constants.CLOSE_NORMAL, message, wait)

    def parse_close(self, content):
        """
        parse_close(content) -> (code, message)

        Parse the given content as the payload of a OP_CLOSE frame, and
        return the error code (as an unsigned integer) and the error
        payload (as a bytes object). If content is empty, the tuple
        (None, None) is returned, to aid round-tripping into close().
        Raises InvalidDataError if the content has a length of 1.
        """
        if not content:
            return (None, None)
        elif len(content) == 1:
            raise InvalidDataError('Invalid close frame payload')
        else:
            return (struct.unpack('!H', content[:2])[0], content[2:])

def wrap(*args, **kwds):
    """
    wrap(file1[, file2], **kwds) -> WebSocket

    Try to wrap file1 and (if given) file2 into a WebSocket.
    Convenience method for static factory methods.
    """
    if len(args) == 0:
        raise TypeError('Cannot wrap nothing')
    elif len(args) == 1:
        f = args[0]
        if hasattr(f, 'recv') and hasattr(f, 'send'):
            return WebSocketFile.from_socket(f, **kwds)
        else:
            return WebSocketFile.from_file(f, **kwds)
    elif len(args) == 2:
        return WebSocketFile.from_files(args[0], args[1], **kwds)
    else:
        raise TypeError('Too many arguments')
