"""
ExpressLRS Backpack bridge
"""

import sys
from collections.abc import Generator, Sequence
from enum import Enum, IntEnum, auto
from typing import Union

from gevent.queue import Queue

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

MSP_HEADER_LENGTH = 8


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


class MSPTypes(IntEnum):
    """
    ExpressLRS Backpack MSP types
    """

    MSP_ELRS_FUNC = 0x4578  # ['E','x']

    MSP_SET_RX_CONFIG = 45
    MSP_VTX_CONFIG = 88  # out message         Get vtx settings - betaflight
    MSP_SET_VTX_CONFIG = 89  # in message          Set vtx settings - betaflight
    MSP_EEPROM_WRITE = 250  # in message          no param

    # ELRS specific opcodes
    MSP_ELRS_RF_MODE = 0x06
    MSP_ELRS_TX_PWR = 0x07
    MSP_ELRS_TLM_RATE = 0x08
    MSP_ELRS_BIND = 0x09
    MSP_ELRS_MODEL_ID = 0x0A
    MSP_ELRS_REQU_VTX_PKT = 0x0B
    MSP_ELRS_SET_TX_BACKPACK_WIFI_MODE = 0x0C
    MSP_ELRS_SET_VRX_BACKPACK_WIFI_MODE = 0x0D
    MSP_ELRS_SET_RX_WIFI_MODE = 0x0E
    MSP_ELRS_SET_RX_LOAN_MODE = 0x0F
    MSP_ELRS_GET_BACKPACK_VERSION = 0x10
    MSP_ELRS_BACKPACK_CRSF_TLM = 0x11
    MSP_ELRS_SET_SEND_UID = 0x00B5
    MSP_ELRS_SET_OSD = 0x00B6

    # CRSF encapsulated msp defines
    ENCAPSULATED_MSP_PAYLOAD_SIZE = 4
    ENCAPSULATED_MSP_FRAME_LEN = 8

    # ELRS backpack protocol opcodes
    # See: https:#docs.google.com/document/d/1u3c7OTiO4sFL2snI-hIo-uRSLfgBK4h16UrbA08Pd6U/edit#heading=h.1xw7en7jmvsj

    # outgoing, packets originating from the backpack or forwarded from the TX backpack to the VRx
    MSP_ELRS_BACKPACK_GET_CHANNEL_INDEX = 0x0300
    MSP_ELRS_BACKPACK_SET_CHANNEL_INDEX = 0x0301
    MSP_ELRS_BACKPACK_GET_FREQUENCY = 0x0302
    MSP_ELRS_BACKPACK_SET_FREQUENCY = 0x0303
    MSP_ELRS_BACKPACK_GET_RECORDING_STATE = 0x0304
    MSP_ELRS_BACKPACK_SET_RECORDING_STATE = 0x0305
    MSP_ELRS_BACKPACK_GET_VRX_MODE = 0x0306
    MSP_ELRS_BACKPACK_SET_VRX_MODE = 0x0307
    MSP_ELRS_BACKPACK_GET_RSSI = 0x0308
    MSP_ELRS_BACKPACK_GET_BATTERY_VOLTAGE = 0x0309
    MSP_ELRS_BACKPACK_GET_FIRMWARE = 0x030A
    MSP_ELRS_BACKPACK_SET_BUZZER = 0x030B
    MSP_ELRS_BACKPACK_SET_OSD_ELEMENT = 0x030C
    MSP_ELRS_BACKPACK_SET_HEAD_TRACKING = (
        0x030D  # enable/disable head-tracking forwarding packets to the TX
    )
    MSP_ELRS_BACKPACK_SET_RTC = 0x030E

    # incoming, packets originating from the VRx
    MSP_ELRS_BACKPACK_SET_MODE = 0x0380  # enable wifi/binding mode
    MSP_ELRS_BACKPACK_GET_VERSION = 0x0381  # get the bacpack firmware version
    MSP_ELRS_BACKPACK_GET_STATUS = 0x0382  # get the status of the backpack
    MSP_ELRS_BACKPACK_SET_PTR = 0x0383  # forwarded back to TX backpack


class MSPPacket:
    """
    Class for managing msp data
    """

    def __init__(self) -> None:
        self._type: MSPPacketType = MSPPacketType.COMMAND
        self._function: Union[MSPTypes, None] = None
        self._payload: bytes | bytearray = bytearray()
        self._flags: int = 0

    @classmethod
    def packets_from_bytes_queue(cls, queue: Queue) -> Generator[Self, None, None]:
        """
        Parses packets from a provided queue

        :param queue: The queue to generate packets from
        :yield: The packet
        """

        def _gen() -> Generator[bytes, None, None]:
            while not queue.is_shutdown:
                yield queue.get()

        for bytes_ in _gen():
            yield from cls.packets_from_bytes(bytes_)

    @classmethod
    def packets_from_bytes(cls, data: bytes) -> Generator[Self, None, None]:
        """
        Parses packets from a provided queue

        :param queue: The queue to generate packets from
        :yield: The packet
        """

        yield from cls._generate_packets((i for i in data))

    @classmethod
    def _generate_packets(
        cls, data: Generator[int, None, None]
    ) -> Generator[Self, None, None]:
        """
        Generates packets from an incoming generator

        :param data: The data generator
        :yield: The generated packet
        """
        state: MSPState = MSPState.IDLE
        type_ = MSPPacketType.UNKNOWN
        flags = 0
        function_: MSPTypes | None = None
        buffer = bytearray()
        length = 0
        crc = 0

        for c in data:

            if state == MSPState.IDLE:
                if c == ord("$"):
                    buffer = bytearray()
                    buffer.append(c)
                    state = MSPState.HEADER_START

            elif state == MSPState.HEADER_START:
                if c == ord("X"):
                    buffer.append(c)
                    state = MSPState.HEADER_X
                else:
                    state = MSPState.IDLE

            elif state == MSPState.HEADER_X:
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

            elif state == MSPState.HEADER_V2_NATIVE:
                buffer.append(c)
                crc = cls._crc8_dvb_s2(crc, c)

                if len(buffer) == MSP_HEADER_LENGTH:
                    flags = buffer[3]
                    function_ = MSPTypes(cls._bytes_to_int(buffer[4:6]))
                    length = cls._bytes_to_int(buffer[6:8])

                    if length == 0:
                        state = MSPState.CHECKSUM_V2_NATIVE
                    else:
                        state = MSPState.PAYLOAD_V2_NATIVE

            elif state == MSPState.PAYLOAD_V2_NATIVE:
                buffer.append(c)
                crc = cls._crc8_dvb_s2(crc, c)

                if len(buffer) - MSP_HEADER_LENGTH == length:
                    state = MSPState.CHECKSUM_V2_NATIVE

            elif state == MSPState.CHECKSUM_V2_NATIVE:
                if c == crc:
                    assert function_ is not None
                    packet = cls()
                    packet.set_type(type_)
                    packet.set_flags(flags)
                    packet.set_function(function_)

                    if len(buffer) - MSP_HEADER_LENGTH > 0:
                        packet.set_payload(buffer[8:])

                    yield packet

                state = MSPState.IDLE

            else:
                state = MSPState.IDLE

    @property
    def function(self) -> Union[MSPTypes, None]:
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

    def set_function(self, function: MSPTypes) -> None:
        """
        Sets the function for the packet

        :param function: The enum to set the function to
        """
        self._function = function

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

    def iterate_payload(self) -> Generator[int, None, None]:
        """
        Yields the data in the packet

        :yield: Payload values
        """
        assert self._payload is not None
        yield from self._payload

    def get_payload_size(self) -> int:
        """
        Gets the size of the payload

        :return: _description_
        """
        return len(self._payload)

    def _payload_size(self) -> bytes:
        return self._int_to_bytes(self.get_payload_size())

    @staticmethod
    def _crc8_dvb_s2(crc: int, a: int) -> int:
        crc = crc ^ a
        for _ in range(8):
            if crc & 0x80:
                crc = (crc << 1) ^ 0xD5
            else:
                crc = crc << 1
        return crc & 0xFF

    @classmethod
    def _calculate_checksum(cls, body: Sequence[int]) -> int:
        crc = 0
        for x in body:
            crc = cls._crc8_dvb_s2(crc, x)
        return crc

    def _create_body(self) -> bytearray:
        assert self._function is not None
        assert self._payload is not None

        body = bytearray()
        body.append(self._flags)
        body += self._int_to_bytes(self._function)
        body += self._payload_size()
        body += self._payload

        return body

    def get_packet(self) -> bytearray:
        """
        Get the constrcuted packet

        :return: The constructed packet
        """
        assert self._type is not MSPPacketType.UNKNOWN

        msp = bytearray()
        msp.append(ord("$"))
        msp.append(ord("X"))
        msp.append(self._type)

        body = self._create_body()
        checksum = self._calculate_checksum(body)

        msp += bytes(body)
        msp.append(checksum)

        return msp
