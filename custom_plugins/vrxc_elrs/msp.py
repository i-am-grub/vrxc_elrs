"""
ExpressLRS Backpack bridge
"""

import sys
from collections.abc import Generator, Sequence
from enum import Enum, IntEnum, auto

from gevent.queue import Queue

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

MSP_HEADER_LENGTH = 8

HEADER_START = ord("$")
HEADER_X = ord("X")


class MSPState(Enum):
    IDLE = auto()
    HEADER_START = auto()
    HEADER_X = auto()
    HEADER_V2_NATIVE = auto()
    PAYLOAD_V2_NATIVE = auto()
    CHECKSUM_V2_NATIVE = auto()
    COMMAND_RECEIVED = auto()


class MSPPacketType(IntEnum):
    UNKNOWN = ord("!")
    COMMAND = ord("<")
    RESPONSE = ord(">")


class MSPFunction(IntEnum):
    """
    VRxC Supported ExpressLRS Backpack MSP types

    See https://github.com/ExpressLRS/Backpack/blob/d15ed3057efc60f5f580b3ed9b1084f4f35a49dd/lib/MSP/msptypes.h
    """

    MSP_ELRS_UNSPECIFIED = 0x0

    MSP_ELRS_GET_BACKPACK_VERSION = 0x10
    MSP_ELRS_SET_SEND_UID = 0x00B5
    MSP_ELRS_SET_OSD = 0x00B6
    MSP_ELRS_BACKPACK_SET_RECORDING_STATE = 0x0305
    MSP_ELRS_BACKPACK_SET_MODE = 0x0380


class MSPSetOSDMode(IntEnum):
    """
    Enums for the Set OSD Command defined by the ExpressLRS Spec
    """

    HEARTBEAT = 0x00
    RELEASE_PORT = 0x01
    CLEAR_SCREEN = 0x02
    WRITE_STRING = 0x03
    DRAW_SCREEN = 0x04


class MSPRecordingState(IntEnum):
    """
    Enums for the Set OSD Command defined by the ExpressLRS Spec
    """

    STOP = 0x00
    START = 0x01


class MSPSetUIDMode(IntEnum):
    """
    Enums for the Set OSD Command defined by the ExpressLRS Spec
    """

    RESET = 0x00
    SET = 0x01


def _crc8_dvb_s2(crc: int, a: int) -> int:
    crc = crc ^ a
    for _ in range(8):
        if crc & 0x80:
            crc = (crc << 1) ^ 0xD5
        else:
            crc = crc << 1
    return crc & 0xFF


class MSPPacket:
    """
    Class for managing msp data
    """

    def __init__(self) -> None:
        self._type: MSPPacketType = MSPPacketType.UNKNOWN
        self._function: MSPFunction = MSPFunction.MSP_ELRS_UNSPECIFIED
        self._payload: bytes = bytes()
        self._flags: int = 0

    @classmethod
    def new_command(cls) -> Self:
        """
        Creates a new packet with the command type set
        """
        c = cls()
        c.set_type(MSPPacketType.COMMAND)
        return c

    @classmethod
    def packets_from_bytes_queue(cls, queue: Queue[bytes]) -> Generator[Self]:
        """
        Parses packets from a provided queue

        :param queue: The queue to generate packets from
        :yield: The packet
        """

        def _bytes_gen() -> Generator[bytes]:
            while not queue.is_shutdown:
                yield queue.get()

        def _int_gen() -> Generator[int]:
            for byte_ in _bytes_gen():
                yield from byte_

        yield from cls._generate_packets(_int_gen())

    @classmethod
    def packets_from_bytes(cls, data: bytes) -> Generator[Self]:
        """
        Parses packets from a provided queue

        :param queue: The queue to generate packets from
        :yield: The packet
        """
        yield from cls._generate_packets((i for i in data))

    @classmethod
    def _generate_packets(cls, data: Generator[int]) -> Generator[Self]:
        """
        Generates packets from a provided generator

        :param data: The data generator
        :yield: The generated packet
        """
        state: MSPState = MSPState.IDLE
        type_ = MSPPacketType.UNKNOWN
        flags = 0
        function_: MSPFunction = MSPFunction.MSP_ELRS_UNSPECIFIED
        buffer = bytearray()
        length = 0
        crc = 0

        for c in data:
            if state is MSPState.IDLE:
                if c == HEADER_START:
                    buffer.clear()
                    buffer.append(c)
                    state = MSPState.HEADER_START

            elif state is MSPState.HEADER_START:
                if c == HEADER_X:
                    buffer.append(c)
                    state = MSPState.HEADER_X
                else:
                    state = MSPState.IDLE

            elif state is MSPState.HEADER_X:
                state = MSPState.HEADER_V2_NATIVE
                crc = 0

                if c in (
                    MSPPacketType.COMMAND,
                    MSPPacketType.RESPONSE,
                ):
                    buffer.append(c)
                    type_ = MSPPacketType(c)
                else:
                    type_ = MSPPacketType.UNKNOWN
                    state = MSPState.IDLE

            elif state is MSPState.HEADER_V2_NATIVE:
                buffer.append(c)
                crc = _crc8_dvb_s2(crc, c)

                if len(buffer) == MSP_HEADER_LENGTH:
                    flags = buffer[3]

                    func_id = cls._bytes_to_int(buffer[4:6])
                    try:
                        function_ = MSPFunction(func_id)
                    except ValueError:
                        state = MSPState.IDLE
                        continue

                    if function_ == MSPFunction.MSP_ELRS_UNSPECIFIED:
                        state = MSPState.IDLE
                        continue

                    length = cls._bytes_to_int(buffer[6:8])

                    if length == 0:
                        state = MSPState.CHECKSUM_V2_NATIVE
                    else:
                        state = MSPState.PAYLOAD_V2_NATIVE

            elif state is MSPState.PAYLOAD_V2_NATIVE:
                buffer.append(c)
                crc = _crc8_dvb_s2(crc, c)

                if len(buffer) - MSP_HEADER_LENGTH == length:
                    state = MSPState.CHECKSUM_V2_NATIVE

            elif state is MSPState.CHECKSUM_V2_NATIVE:
                if c == crc:
                    packet = cls()
                    packet.set_type(type_)
                    packet.set_flags(flags)
                    packet.set_function(function_)

                    if len(buffer) - MSP_HEADER_LENGTH > 0:
                        packet.set_payload(buffer[8:])

                    yield packet

                state = MSPState.IDLE

    @property
    def function(self) -> MSPFunction | None:
        """
        Getter for the packet's function
        """
        return self._function

    @property
    def type_(self) -> MSPPacketType:
        """
        Getter for the packet's type
        """
        return self._type

    @property
    def payload(self) -> bytes:
        """
        Getter for the packet's type
        """
        return self._payload

    @staticmethod
    def _int_to_bytes(a: int) -> bytes:
        return a.to_bytes(2, "little")

    @staticmethod
    def _bytes_to_int(a: bytes | bytearray) -> int:
        return int.from_bytes(a, "little")

    def set_function(self, function: MSPFunction | int) -> None:
        """
        Sets the function for the packet

        :param function: The enum to set the function to
        """
        self._function = MSPFunction(function)

    def set_payload(self, payload: Sequence[int] | bytes) -> None:
        """
        Sets the payload for the packet

        :param payload: The payload of the packet
        """
        self._payload = bytes(payload)

    def set_flags(self, flags: int) -> None:
        """
        Sets the payload for the packet

        :param payload: The payload of the packet
        """
        self._flags = flags

    def set_type(self, type_: MSPPacketType) -> None:
        """
        Sets the payload for the packet

        :param payload: The payload of the packet
        """
        self._type = type_

    def iterate_payload(self) -> Generator[int]:
        """
        Yields the data in the packet

        :yield: Payload values
        """
        yield from self._payload

    def get_payload_size(self) -> int:
        """
        Gets the size of the payload

        :return: _description_
        """
        return len(self._payload)

    def _payload_size(self) -> bytes:
        return self._int_to_bytes(self.get_payload_size())

    @classmethod
    def _calculate_checksum(cls, body: Sequence[int]) -> int:
        crc = 0
        for x in body:
            crc = _crc8_dvb_s2(crc, x)
        return crc

    def _create_body(self) -> bytearray:
        body = bytearray()
        body.append(self._flags)
        body += self._int_to_bytes(self._function)
        body += self._payload_size()
        body += self._payload

        return body

    def get_packet(self) -> bytes:
        """
        Get the constrcuted packet

        :return: The constructed packet
        """
        if (
            self._type is MSPPacketType.UNKNOWN
            or self._function is MSPFunction.MSP_ELRS_UNSPECIFIED
        ):
            msg = "Packet type or function is unset"
            raise ValueError(msg)

        msp = bytearray()
        msp.append(HEADER_START)
        msp.append(HEADER_X)
        msp.append(self._type)

        body = self._create_body()
        checksum = self._calculate_checksum(body)

        msp += bytes(body)
        msp.append(checksum)

        return bytes(msp)
