# websocket_server -- WebSocket/HTTP server/client library
# https://github.com/CylonicRaider/websocket-server

"""
WebSocket protocol implementation.

client_handshake() and server_handshake() perform the appropriate operations
on mappings of HTTP headers; the WebSocketFile class implements the framing
protocol.
"""

import os
import socket
import struct
import base64
import codecs
import threading
import hashlib
from collections import namedtuple

from . import constants
from .compat import bytearray, bytes, tobytes, unicode, callable
from .exceptions import ProtocolError, InvalidDataError
from .exceptions import ConnectionClosedError
from .tools import mask, new_mask

__all__ = ['client_handshake', 'WebSocketFile', 'wrap']

# Allocation unit.
BUFFER_SIZE = 16384

# Frame class
Frame = namedtuple('Frame', 'opcode payload final msgtype')

# Message class
Message = namedtuple('Message', 'msgtype content final')

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
# +-------------------------------+ - - - - - - - - - - - - - - - +
# :                     Payload Data continued ...                :
# + - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - +
# |                     Payload Data continued ...                |
# +---------------------------------------------------------------+

# The "magic" GUID used for Sec-WebSocket-Accept.
MAGIC_GUID = unicode('258EAFA5-E914-47DA-95CA-C5AB0DC85B11')

def process_key(key):
    """
    process_key(key) -> unicode

    Transform the given key as required to form a Sec-WebSocket-Accept
    field, and return the new key.
    """
    enc_key = (unicode(key) + MAGIC_GUID).encode('ascii')
    resp_key = base64.b64encode(hashlib.sha1(enc_key).digest())
    return resp_key.decode('ascii')

def client_handshake(headers, protos=None, makekey=None):
    """
    client_handshake(headers, protos=None, makekey=None) -> function

    Perform the client-side parts of a WebSocket handshake.
    headers is a mapping from header names to header values (both Unicode
    strings) which is modified in-place with WebSocket headers.
    protos is one of:
    - None to not advertise subprotocols,
    - A single string used directly as the Sec-WebSocket-Protocol header,
    - A list of strings, which are joined by commata into the value of the
      Sec-WebSocket-Protocol header.
    NOTE that the value of protos is not validated.
    makekey, if not None, is a function that returns a byte string of length
    16 that is used as the base of the Sec-WebSocket-Key header. If makekey
    is None, os.urandom() is used.
    The return value is a function that takes the response headers (in the
    same format as headers) as the only parameter and raises a ProtocolError
    if the handshake is not successful. If the handshake *is* successful, the
    function returns the subprotocol selected by the server (a string that
    must have been present in protos), or None (for no subprotocol).
    NOTE that this library does not support extensions. For future
         compatibility, it would be prudent to specify makekey, if at all,
         as a keyword argument.
    """
    def check_response(respheaders):
        "Ensure the given HTTP response headers are a valid WS handshake."
        # Verify key and other fields.
        if respheaders.get('Sec-WebSocket-Accept') != process_key(key):
            raise ProtocolError('Invalid response key')
        if respheaders.get('Sec-WebSocket-Extensions'):
            raise ProtocolError('Extensions not supported')
        p = respheaders.get('Sec-WebSocket-Protocol')
        # If protos is None, using the "in" operator may fail.
        if p and (not protos or p not in protos):
            raise ProtocolError('Invalid subprotocol received')
        return p
    if makekey is None: makekey = lambda: os.urandom(16)
    headers.update({'Connection': 'Upgrade', 'Upgrade': 'websocket',
        'Sec-WebSocket-Version': '13'})
    if isinstance(protos, str):
        headers['Sec-WebSocket-Protocol'] = protos
    elif protos is not None:
        headers['Sec-WebSocket-Protocol'] = ', '.join(protos)
    key = base64.b64encode(makekey()).decode('ascii')
    headers['Sec-WebSocket-Key'] = key
    return check_response

def server_handshake(headers, protos=None):
    """
    server_handshake(headers, protos=None) -> dict

    Perform the server-side part of a WebSocket handshake.
    headers is a maping from header names to header values (both Unicode
    strings), which is validated.
    protos is one of:
    - None to indicate no subprotocols,
    - A sequence or whitespace-delimited string of names of accepted
      subprotocols (the first subprotocol proposed by the client that is
      in the list is selected),
    - A function taking the list of subprotocols proposed by the client as
      the only argument and returning a subprotocol name or None.
    The return value is a mapping of headers to be included in the response.
    """
    def error(msg): raise ProtocolError('Invalid handshake: %s' % msg)
    # The standard requires a Host header... why not...
    if 'Host' not in headers:
        error('Missing Host header')
    # Validate Upgrade header.
    if 'websocket' not in headers.get('Upgrade', '').lower():
        error('Invalid/Missing Upgrade header')
    # Validate protocol version.
    if headers.get('Sec-WebSocket-Version') != '13':
        error('Invalid WebSocket version (!= 13)')
    # Validate Connection header.
    connection = [i.lower().strip()
                  for i in headers.get('Connection', '').split(',')]
    if 'upgrade' not in connection:
        error('Invalid/Missing Connection header')
    # Validate the key.
    key = headers.get('Sec-WebSocket-Key')
    try:
        if len(base64.b64decode(tobytes(key))) != 16:
            error('Invalid WebSocket key length')
    except (TypeError, ValueError):
        error('Invalid WebSocket key')
    # Extensions are not supported.
    # Be permissive with subprotocol tokens.
    protstr = headers.get('Sec-WebSocket-Protocol', '')
    protlist = ([i.strip() for i in protstr.split(',')] if protstr else [])
    if protos is None:
        respproto = None
    elif callable(protos):
        respproto = protos(protlist)
    else:
        if isinstance(protos, str): protos = protos.split()
        # Intentionally leaking loop variable.
        for respproto in protlist:
            if respproto in protos: break
        else:
            respproto = None
    # Prepare response headers.
    ret = {'Connection': 'upgrade', 'Upgrade': 'websocket',
           'Sec-WebSocket-Accept': process_key(key)}
    if respproto is not None:
        ret['Sec-WebSocket-Protocol'] = respproto
    return ret

class WebSocketFile(object):
    """
    WebSocket protocol implementation. May base on a pair of file-like
    objects (for usage in HTTPRequestHandler's); a "raw" socket (if you
    prefer parsing HTTP headers yourself); or a single file object (if
    you have got such a read-write one). This class is not concerned
    with the handshake; see client_handshake() and server_handshake() for
    that.

    WebSocketFile(rdfile, wrfile, server_side=False, subprotocol=None)
    rdfile     : File to perform reading operations on.
    wrfile     : File to perform writing operations on.
    server_side: Whether to engage server-side behavior (if true) or not
                 (otherwise).
    subprotocol: The subprotocol to be used.

    Attributes:
    server_side  : Whether this is a server-side WebSocketFile.
    subprotocol  : The subprotocol as passed to the constructor.
    close_wrapped: Whether calling close() should close the underlying
                   files as well. Defaults to True.
    _rdlock      : threading.RLock instance used for serializing and
                   protecting reading-related operations.
    _wrlock      : threading.RLock instance user for serializing and
                   protecting write-related operations.
                   _rdlock should always be asserted before _wrlock, if at
                   all; generally, do not call reading-related methods
                   (which also include close*()) with _wrlock asserted,
                   and do not use those locks unless necessary.
    _socket      : Underlying socket (set by from_socket()).
                   May not be present at all (i.e. be None). Only use this
                   if you are really sure you need to.

    Class attributes:
    MAXFRAME    : Maximum frame payload length. May be overridden by
                  subclasses (or instances). Value is either an integer or
                  None (indicating no limit). This is not enforced for
                  outgoing messages.
    MAXCONTFRAME: Maximum length of a frame reconstructed from fragments.
                  May be overridden as well. The value has the same
                  semantics as the one of MAXFRAME. This is not enforced
                  for outgoing messages as well.

    NOTE: This class reads exactly the amount of bytes needed, yet
          buffering of the underlying stream may cause frames to
          "congest".
          The underlying stream must be blocking, or unpredictable
          behavior occurs.
    """

    # Maximum allowed frame length.
    MAXFRAME = None

    # Maximum continued frame length.
    MAXCONTFRAME = None

    @classmethod
    def from_files(cls, rdfile, wrfile, **kwds):
        """
        from_files(rdfile, wrfile, **kwds) -> WebSocketFile

        Equivalent to the constructor; provided for symmetry.
        """
        return cls(rdfile, wrfile, **kwds)

    @classmethod
    def from_socket(cls, sock, **kwds):
        """
        from_socket(sock, **kwds) -> WebSocketFile

        Wrap a socket in a WebSocketFile. Uses the makefile() method to
        obtain the file objects internally used. Keyword arguments are passed
        on to the constructor.
        """
        ret = cls.from_file(sock.makefile('rwb'), **kwds)
        ret._socket = sock
        return ret

    @classmethod
    def from_file(cls, file, **kwds):
        """
        from_file(file, **kwds) -> WebSocketFile

        Wrap a read-write file object. Keyword arguments are passed on to the
        constructor.
        """
        return cls(file, file, **kwds)

    def __init__(self, rdfile, wrfile, server_side=False, subprotocol=None):
        """
        __init__(rdfile, wrfile, server_side=False, subprotocol=None) -> None

        See the class docstring for details.
        """
        self._rdfile = rdfile
        self._wrfile = wrfile
        self._socket = None
        self.server_side = server_side
        self.subprotocol = subprotocol
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

    def _shutdown_raw(self, mode):
        """
        _shutdown_raw(mode) -> None

        Perform a shutdown of the underlying socket, if any. mode is a
        socket.SHUT_* constant denoting the precise mode of shutdown.
        """
        s = self._socket
        if s:
            try:
                s.shutdown(mode)
            except socket.error:
                pass

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
        invalid, is truncated, an invalid (non-)continuation frame is
        read, EOF inside an unfinished fragmented frame is encountered,
        etc.
        WARNING: If a control frame is received (i.e. whose opcode
                 bitwise-AND OPMASK_CONTROL is nonzero), it must be
                 passed into the handle_control() method; otherwise.
                 the implementation may misbehave.
        """
        with self._rdlock:
            # Store for later.
            was_read_close = self._read_close
            # No more reading after close.
            if was_read_close: return None
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
                        if self._cur_opcode is None:
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
                    length = struct.unpack('!H', buf[:2])[0]
                    # Validate length
                    if length < 126:
                        self._error('Invalid frame length encoding')
                    if masked: msk = buf[2:6]
                elif length == 127:
                    buf = self._readinto_raw(8 + masklen)
                    length = struct.unpack('!Q', buf[:8])[0]
                    # Validate length.
                    if length < 65536:
                        self._error('Invalid frame length encoding')
                    elif length >= 9223372036854775808: # 2 ** 63
                        # MUST in RFC 6455, section 5.2
                        # We could handle those frames easily (given we have
                        # enough memory), though.
                        self._error('Frame too long')
                    if masked: msk = buf[8:12]
                # Validate length.
                if self.MAXFRAME is not None and length > self.MAXFRAME:
                    self.error('Frame too long',
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
        read_frame(stream=False) -> (msgtype, content, final) or None

        Read a WebSocket data frame.
        The return value is composed from fields of the same meaning as
        from read_single_frame(). Note that the opcode field is discarded
        in favor of msgtype. The return value is (as in
        read_single_frame()), a named tuple, with the field names as
        indicated. If the stream encounters an EOF, returns None.
        If stream is false, fragmented frames are re-combined into a
        single frame (MAXCONTFRAME is applied), otherwise, they are
        returned individually.
        If the beginning of a fragmented frame was already consumed, the
        remainder of it (or one frame of the remainder, depending on
        stream) is read.
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
                if fr.msgtype == constants.OP_TEXT:
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
                    self.error('Fragmented frame too long',
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
        The return value tells whether it is safe to continue reading
        (true), or if EOF (i.e. a close frame) was reached (false).
        """
        if opcode == constants.OP_PING:
            self.write_single_frame(constants.OP_PONG, cnt)
        elif opcode == constants.OP_CLOSE:
            self._read_close = True
            self._shutdown_raw(socket.SHUT_RD)
            self.close_ex(*self.parse_close(cnt))
            return False
        return True

    def _error(self, message):
        "Used internally."
        self.error(message)
        # Assure execution does not continue.
        raise RuntimeError('error() returned')

    def error(self, message, code=constants.CLOSE_PROTOCOL_FAILURE):
        """
        error(message, code=CLOSE_PROTOCOL_FAILURE) -> [ProtocolError]

        Initiate an abnormal connection close and raise a ProtocolError.
        code is the error code to use.
        This method is called from read_single_frame() if an invalid
        frame is detected.
        """
        # We will hardly be able to interpret anything the other side emits
        # at this point.
        self._read_close = True
        self.close_ex(code, message)
        raise ProtocolError(message, code=code)

    def write_single_frame(self, opcode, data, final=True, maskkey=None):
        """
        write_single_frame(opcode, data, final=True, maskkey=None) -> None

        Write a frame with the given parameters.
        final determines whether the frame is final; opcode is one of the
        OP_* constants; data is the payload of the message. maskkey, if
        not None, is a length-four byte sequence that determines which
        mask key to use, otherwise, tools.new_mask() will be invoked to
        create one if necessary.
        If opcode is OP_TEXT, data may be a Unicode or a byte string,
        otherwise, data must be a byte string. If the type of data is
        inappropriate, TypeError is raised.
        Raises ConnectionClosedError is the connection is already closed
        or closing.
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

    def close_now(self, force=False):
        """
        close_now(force=False) -> None

        Close the underlying files immediately. If force is true, they are
        closed unconditionally, otherwise only if the close_wrapped attribute
        is true.
        This does not perform a proper closing handshake and should be
        avoided in favor of close().
        """
        # Waiting for locks contradicts the "now!" intention, so none of that
        # here.
        self._read_close = True
        self._written_close = True
        self._closed = True
        if force or self.close_wrapped:
            self._shutdown_raw(socket.SHUT_RDWR)
            try:
                self._rdfile.close()
            except IOError:
                pass
            try:
                self._wrfile.close()
            except IOError:
                pass
            if self._socket:
                try:
                    self._socket.close()
                except socket.error:
                    pass

    def close_ex(self, code=None, message=None, wait=True):
        """
        close_ex(code=None, message=None, wait=True) -> None

        Close the underlying connection, delivering the code and message
        (if given) to the other point. If code is None, message is
        ignored. If message is a Unicode string, it is encoded using
        UTF-8. If wait is true, this will read frames from self and discard
        them until the other side acknowledges the close; as this may cause
        data loss, be careful. The default is to ensure the WebSocket is
        fully closed when the call finishes; when closing a WebSocket that
        is read from in a different thread, specify wait=False and let the
        other thread consume any remaining input.
        If the connection is already closed, the method has no effect
        (but might raise an exception if encoding code or message fails).
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
                if self._read_close:
                    if not self._closed:
                        self.close_now()
                    wait = False
            else:
                # Write close frame.
                self.write_single_frame(constants.OP_CLOSE, payload)
                # Close frame written.
                self._written_close = True
                self._shutdown_raw(socket.SHUT_WR)
        # Wait for close if desired.
        if wait:
            with self._rdlock:
                while self.read_frame(True): pass
            self.close_ex(wait=False)

    def close(self, message=None, wait=True):
        """
        close(message=None, wait=True) -> None

        Close the underlying connection with a code of CLOSE_NORMAL and
        the (optional) given message. If wait is true, this will read
        frames from self until the other side acknowledges the close; as
        this may cause data loss, be careful.
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
    Convenience method for static factory methods: If both file1 and file2 are
    given, they are passed to from_files(); if otherwise file1 has recv and
    send attributes, it is passed to from_socket(), otherwise, it is passed to
    from_file().
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
