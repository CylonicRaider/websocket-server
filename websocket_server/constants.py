# websocket_server -- WebSocket server library
# https://github.com/CylonicRaider/websocket-server

"""
Various (numeric) constants.
"""

# Opcode constants.

# Individual constants
OP_CONT   = 0x00 # Continuation frame
OP_TEXT   = 0x01 # Text frame
OP_BINARY = 0x02 # Binary frame
OP_CLOSE  = 0x08 # Close frame
OP_PING   = 0x09 # Ping frame
OP_PONG   = 0x0A # Pong frame

OP_MIN    = 0x00 # Minimum possible opcode.
OP_MAX    = 0x0F # Maximum possible opcode.

# Bitmasks
OPMASK_CONTROL = 0x08 # Is the given opcode a control one?

# Value-to-opcode mapping
OPCODES = {OP_CONT : 'CONT' , OP_TEXT: 'TEXT', OP_BINARY: 'BINARY',
           OP_CLOSE: 'CLOSE', OP_PING: 'PING', OP_PONG  : 'PONG'  }

# Opcode-to-value mapping
REV_OPCODES = {}
for k, v in OPCODES.items(): REV_OPCODES[v] = k

# Packet flag masks.

# Opcode byte
FLAG_FIN    = 0x80 # Final frame
FLAG_RSV1   = 0x40 # Reserved 1
FLAG_RSV2   = 0x20 # Reserved 2
FLAG_RSV3   = 0x10 # Reserved 3

MASK_RSV    = 0x70 # All reserved flags
MASK_OPCODE = 0x0F # Opcode mask inside its byte

# Length byte
FLAG_MASK   = 0x80 # Masked frame

MASK_LENGTH = 0x7F # Length mask inside its byte

# Closing codes.

# Individual constants
CLOSE_NORMAL               = 1000
CLOSE_GOING_AWAY           = 1001
CLOSE_PROTOCOL_FAILURE     = 1002
CLOSE_UNACCEPTABLE_DATA    = 1003
CLOSE_NO_STATUS            = 1005
CLOSE_ABNORMAL             = 1006
CLOSE_INCONSISTENT_DATA    = 1007
CLOSE_POLICY_VIOLATION     = 1008
CLOSE_MESSAGE_TOO_BIG      = 1009
CLOSE_EXPECTED_EXTENSION   = 1010
CLOSE_UNEXPECTED_CONDITION = 1011
CLOSE_TLS_FAILURE          = 1015

# Value-to-name mapping
CLOSES = {CLOSE_NORMAL              : 'NORMAL',
          CLOSE_GOING_AWAY          : 'GOING_AWAY',
          CLOSE_PROTOCOL_FAILURE    : 'PROTOCOL_FAILURE',
          CLOSE_UNACCEPTABLE_DATA   : 'UNACCEPTABLE_DATA',
          CLOSE_NO_STATUS           : 'NO_STATUS',
          CLOSE_ABNORMAL            : 'ABNORMAL',
          CLOSE_INCONSISTENT_DATA   : 'INCONSISTENT_DATA',
          CLOSE_POLICY_VIOLATION    : 'POLICY_VIOLATION',
          CLOSE_MESSAGE_TOO_BIG     : 'MESSAGE_TOO_BIG',
          CLOSE_EXPECTED_EXTENSION  : 'EXPECTED_EXTENSION',
          CLOSE_UNEXPECTED_CONDITION: 'UNEXPECTED_CONDITION',
          CLOSE_TLS_FAILURE         : 'TLS_FAILURE'}

# Name-to-value mapping
REV_CLOSES = {}
for k, v in CLOSES.items(): REV_CLOSES[v] = k

# Values interesting for an import *.
__all__ = (['OP_%s' % i for i in REV_OPCODES.keys()] +
           ['CLOSE_%s' % i for i in REV_CLOSES.keys()] +
           ['OPCODES', 'REV_OPCODES', 'CLOSES', 'REV_CLOSES'])
