import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from functools import partial
from typing import final

import gevent
import gevent.queue
import gevent.socket as socket
import serial
import serial.tools.list_ports
from gevent.queue import Queue

from .msp import MSPFunction, MSPPacket, MSPPacketType

SOCKET_PORT = 8080
AVOIDED_PORTS = {"/dev/ttyAMA0", "/dev/ttyAMA10", "COM1"}

logger = logging.getLogger(__name__)

BackpackSerial = partial(
    serial.Serial,
    baudrate=460800,
    bytesize=8,
    parity="N",
    stopbits=1,
    timeout=5,
    xonxoff=0,
    rtscts=0,
    write_timeout=5,
)


class BackpackConnection(ABC):
    """
    Protocol for backpack connections
    """

    @abstractmethod
    def __init__(
        self, send_queue: Queue[MSPPacket], recieve_queue: Queue[MSPPacket]
    ): ...

    @property
    @abstractmethod
    def connected(self) -> bool: ...

    @abstractmethod
    def connect(self) -> bool: ...

    @abstractmethod
    def disconnect(self): ...


@dataclass
class ConnectionType:
    """
    Dataclass for custom connection enum
    """

    type_: type["BackpackConnection"]
    id_: int


class SerialConnection(BackpackConnection):
    """
    Backpack over serial connection
    """

    def __init__(self, send_queue, recieve_queue):
        self._connected = False
        self._send_queue = send_queue
        self._recieve_queue = recieve_queue
        self._connection: serial.Serial | None = None
        self._parsing_queue: gevent.queue.Queue[bytes] = gevent.queue.Queue()

        self._send_greenlet: gevent.Greenlet | None = None
        self._recieve_greenlet: gevent.Greenlet | None = None
        self._parsing_greenlet: gevent.Greenlet | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        packet = MSPPacket()
        packet.set_function(MSPFunction.MSP_ELRS_GET_BACKPACK_VERSION)

        logger.info("Attempting to find backpack")

        avaliable_port = {port.device for port in serial.tools.list_ports.comports()}

        for port in avaliable_port - AVOIDED_PORTS:
            try:
                connection = BackpackSerial(port=port)
            except:
                logger.warning(
                    "Failed to open serial device. Attempting to connect to new device..."
                )
                continue

            # Some devkits need extra time to establish the connection
            gevent.sleep(2)

            # Clear out any previous data in the serial buffer
            connection.read_all()

            try:
                connection.write(packet.get_packet())
            except:
                logger.error(
                    "Failed to write to open serial device. Attempting to connect to new device..."
                )
                connection.close()
                continue

            gevent.sleep(0.2)

            data = connection.read_all()
            for packet in MSPPacket.packets_from_bytes(data):
                if (
                    packet.type_ == MSPPacketType.RESPONSE
                    and packet.function == MSPFunction.MSP_ELRS_GET_BACKPACK_VERSION
                ):
                    self._connection = connection
                    self._connected = True
                    break

            if self._connected:
                break

        else:
            return False

        self._parsing_greenlet = gevent.spawn(self._parser)
        self._send_greenlet = gevent.spawn(self._send)
        self._recieve_greenlet = gevent.spawn(self._recieve)
        return True

    def _send(self) -> None:
        """
        Sends data from the queue over the socket
        """
        assert self._connection is not None

        try:
            while self._connected:
                packet: MSPPacket = self._send_queue.get()
                self._connection.write(packet.get_packet())

        finally:
            self._connected = False
            self._send_greenlet = None
            self.disconnect()

    def _parser(self) -> None:
        """
        Parses incoming data
        """
        for packet in MSPPacket.packets_from_bytes_queue(self._parsing_queue):
            self._recieve_queue.put(packet)

    def _recieve(self) -> None:
        """
        Recieves data from the socket and adds it to the queue
        """
        if self._connection is None:
            msg = "Connection is not active"
            raise RuntimeError(msg)

        try:
            while self._connected:
                data = self._connection.read_all()
                self._parsing_queue.put(data)
                gevent.sleep(0.2)

        finally:
            self._connected = False
            self._recieve_greenlet = None
            self.disconnect()

    def disconnect(self):
        """
        _summary_
        """
        self._connected = False

        if self._parsing_greenlet is not None:
            self._parsing_greenlet.kill()

        if self._send_greenlet is not None:
            self._send_greenlet.kill()

        if self._recieve_greenlet is not None:
            self._recieve_greenlet.kill()

        if self._connection is not None:
            self._connection.close()
            self._connection = None


@final
class SocketConnection(BackpackConnection):
    """
    Backpack over socket connection
    """

    def __init__(self, send_queue, recieve_queue, ip_addr: str):
        self._connected = False
        self._send_queue = send_queue
        self._recieve_queue = recieve_queue
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        self._send_greenlet: gevent.Greenlet | None = None
        self._recieve_greenlet: gevent.Greenlet | None = None
        self._ip_addr = ip_addr

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        """
        Establishes the socket connection

        :param ip_addr: The IP address to connect to
        """
        self._socket.settimeout(5)
        packet = MSPPacket()
        packet.set_function(MSPFunction.MSP_ELRS_GET_BACKPACK_VERSION)

        try:
            self._socket.connect((self._ip_addr, SOCKET_PORT))
            self._socket.sendall(packet.get_packet())
            data = self._socket.recv(128)
            for packet in MSPPacket.packets_from_bytes(data):
                if (
                    packet.type_ == MSPPacketType.RESPONSE
                    and packet.function == MSPFunction.MSP_ELRS_GET_BACKPACK_VERSION
                ):
                    self._connected = True
                    break
            else:
                self._socket.close()
                return False

        except TimeoutError:
            self._socket.close()
            return False

        self._socket.settimeout(None)

        self._send_greenlet = gevent.spawn(self._send)
        self._recieve_greenlet = gevent.spawn(self._recieve)

        return True

    def _send(self) -> None:
        """
        Sends data from the queue over the socket
        """
        try:
            while self._connected:
                packet: MSPPacket = self._send_queue.get()

                timeout = gevent.Timeout(1)
                timeout.start()
                try:
                    self._socket.sendall(packet.get_packet())
                finally:
                    timeout.close()
        except gevent._socketcommon.cancel_wait_ex:
            ...

        finally:
            self._connected = False
            self._send_greenlet = None
            self.disconnect()

    def _recieve(self) -> None:
        """
        Recieves data from the socket and adds it to the queue
        """
        try:
            while self._connected:
                data = self._socket.recv(128)
                for packet in MSPPacket.packets_from_bytes(data):
                    self._recieve_queue.put(packet)
        except gevent._socketcommon.cancel_wait_ex:
            ...

        finally:
            self._connected = False
            self._recieve_greenlet = None
            self.disconnect()

    def disconnect(self):
        """
        Disconnects the socket
        """
        self._connected = False

        if self._send_greenlet is not None:
            self._send_greenlet.kill()

        if self._recieve_greenlet is not None:
            self._recieve_greenlet.kill()

        self._socket.close()


class ConnectionTypeEnum(ConnectionType, Enum):
    """
    Enum for different connection selections
    """

    USB = SerialConnection, 1
    ONBOARD = SerialConnection, 2
    SOCKET = SocketConnection, 3
