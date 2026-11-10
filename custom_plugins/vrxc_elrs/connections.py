import logging
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Union

import gevent
import gevent.queue
import gevent.socket as socket
import serial
import serial.tools.list_ports
from gevent.queue import Queue

from .msp import MSPPacket, MSPPacketType, MSPTypes

SOCKET_PORT = 8080
AVOIDED_PORTS = {"/dev/ttyAMA0", "/dev/ttyAMA10", "COM1"}

logger = logging.getLogger(__name__)


class BackpackConnection(Protocol):
    """
    Protocol for backpack connections
    """

    connected: bool

    def __init__(self, send_queue: Queue, recieve_queue: Queue): ...

    def connect(self, **kwargs) -> bool: ...

    def disconnect(self): ...


@dataclass
class ConnectionType:
    """
    Dataclass for custom connection enum
    """

    type_: type["BackpackConnection"]
    id_: int


class SerialConnection:
    """
    Backpack over serial connection
    """

    _send_greenlet: Union[gevent.Greenlet, None] = None
    _recieve_greenlet: Union[gevent.Greenlet, None] = None
    _parsing_greenlet: Union[gevent.Greenlet, None] = None

    def __init__(self, send_queue: Queue, recieve_queue: Queue):
        self._connected = False
        self._send_queue = send_queue
        self._recieve_queue = recieve_queue
        self._connection: Union[serial.Serial, None] = None
        self._parsing_queue = gevent.queue.Queue()

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self, port: Union[str, None] = None) -> bool:
        request = MSPPacket()
        request.set_function(MSPTypes.MSP_ELRS_GET_BACKPACK_VERSION)

        port = (port or "").strip()
        if port:
            logger.info("Connecting to backpack at configured USB path %s", port)
            ports = [port]
        else:
            logger.info("Attempting to find backpack")
            ports = sorted(
                {device.device for device in serial.tools.list_ports.comports()}
                - AVOIDED_PORTS
            )

        for port in ports:
            connection = None
            try:
                connection = serial.Serial(
                    port=port,
                    baudrate=460800,
                    bytesize=8,
                    parity="N",
                    stopbits=1,
                    timeout=5,
                    xonxoff=0,
                    rtscts=0,
                    write_timeout=5,
                )
                # Some devkits need extra time to establish the connection.
                gevent.sleep(2)
                connection.read_all()
                connection.write(request.get_packet())
                gevent.sleep(0.2)

                data = connection.read_all()
                for packet in MSPPacket.packets_from_bytes(data):
                    if (
                        packet.type_ == MSPPacketType.RESPONSE
                        and packet.function == MSPTypes.MSP_ELRS_GET_BACKPACK_VERSION
                    ):
                        self._connection = connection
                        self._connected = True
                        break

                if self._connected:
                    logger.info("Found backpack at %s", port)
                    break

                logger.warning("No backpack version response from %s", port)
            except (OSError, serial.SerialException) as exc:
                logger.warning("Failed to connect to serial device %s: %s", port, exc)
            finally:
                # Release failed candidates, including other plugins' devices.
                if connection is not None and not self._connected:
                    connection.close()

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
        assert self._connection is not None

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

        self._connection.close()


class SocketConnection:
    """
    Backpack over socket connection
    """

    _send_greenlet: Union[gevent.Greenlet, None] = None
    _recieve_greenlet: Union[gevent.Greenlet, None] = None

    def __init__(self, send_queue: Queue, recieve_queue: Queue):
        self._connected = False
        self._send_queue = send_queue
        self._recieve_queue = recieve_queue
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self, ip_addr: str) -> bool:
        """
        Establishes the socket connection

        :param ip_addr: The IP address to connect to
        """
        self._socket.settimeout(5)
        packet = MSPPacket()
        packet.set_function(MSPTypes.MSP_ELRS_GET_BACKPACK_VERSION)

        try:
            self._socket.connect((ip_addr, SOCKET_PORT))
            self._socket.sendall(packet.get_packet())
            data = self._socket.recv(128)
            for packet in MSPPacket.packets_from_bytes(data):
                if (
                    packet.type_ == MSPPacketType.RESPONSE
                    and packet.function == MSPTypes.MSP_ELRS_GET_BACKPACK_VERSION
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
