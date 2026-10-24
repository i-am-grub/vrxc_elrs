import base64
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

from .msp import MSP_HEADER_LENGTH, MSPPacket, MSPPacketType, MSPTypes

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

    def connect(self) -> bool:
        packet = MSPPacket()
        packet.set_function(MSPTypes.MSP_ELRS_GET_BACKPACK_VERSION)

        logger.info("Attempting to find backpack")

        avaliable_port = {port.device for port in serial.tools.list_ports.comports()}

        for port in avaliable_port - AVOIDED_PORTS:

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
                    and packet.function == MSPTypes.MSP_ELRS_GET_BACKPACK_VERSION
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


class WebBridge:
    """
    Shared state between the browser bridge page (Web Serial, running on the
    PC the ESP is plugged into) and the active `WebConnection`.

    The page opens the serial port and reports its state over socket.io;
    MSP bytes then flow in both directions through socket.io events.
    """

    TX_EVENT = "elrs_web_tx"
    RX_EVENT = "elrs_web_rx"

    def __init__(self) -> None:
        self.rhapi = None
        self.controller = None
        self.open = False
        self.connection: Union["WebConnection", None] = None

    def broadcast(self, data: bytes) -> None:
        """
        Sends raw MSP bytes to the browser page(s)
        """
        assert self.rhapi is not None
        self.rhapi.ui.socket_broadcast(
            self.TX_EVENT, {"d": base64.b64encode(data).decode("ascii")}
        )

    def on_state(self, data: dict) -> None:
        """
        The browser opened or closed the ESP serial port
        """
        self.open = bool(data.get("open"))
        logger.info("Browser bridge serial port %s", "open" if self.open else "closed")

        if self.controller is None:
            return

        if self.open:
            if self.connection is None or not self.connection.connected:
                self.controller.start_connection_if_web()
        elif self.connection is not None and self.connection.connected:
            self.connection.disconnect()

    def on_rx(self, data: dict) -> None:
        """
        Bytes read from the ESP by the browser
        """
        if self.connection is None:
            return

        try:
            raw = base64.b64decode(data.get("d", ""))
        except ValueError:
            return

        self.connection.feed(raw)


web_bridge = WebBridge()


class WebConnection:
    """
    Backpack over a browser (Web Serial) bridge
    """

    _send_greenlet: Union[gevent.Greenlet, None] = None

    def __init__(self, send_queue: Queue, recieve_queue: Queue):
        self._connected = False
        self._send_queue = send_queue
        self._recieve_queue = recieve_queue
        self._buffer = bytearray()

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        if not web_bridge.open:
            logger.warning(
                "No browser bridge connected. Open /elrs_web on the PC and connect the ESP."
            )
            return False

        self._connected = True
        web_bridge.connection = self

        self._send_greenlet = gevent.spawn(self._send)
        return True

    def feed(self, data: bytes) -> None:
        """
        Adds bytes received from the browser, and queues every complete
        MSP v2 frame (`$X<type> flags func(2) len(2) payload crc`).
        Browsers split serial data at arbitrary points, so frames can
        arrive in several pieces.
        """
        self._buffer += data

        while True:
            start = self._buffer.find(b"$X")
            if start < 0:
                # Keep a trailing "$" that may be the start of the next frame
                del self._buffer[: len(self._buffer) - (self._buffer[-1:] == b"$")]
                return
            del self._buffer[:start]

            if len(self._buffer) < MSP_HEADER_LENGTH:
                return

            frame_len = MSP_HEADER_LENGTH + int.from_bytes(self._buffer[6:8], "little") + 1
            if len(self._buffer) < frame_len:
                return

            frame = bytes(self._buffer[:frame_len])
            del self._buffer[:frame_len]

            try:
                for packet in MSPPacket.packets_from_bytes(frame):
                    self._recieve_queue.put(packet)
            except ValueError:
                logger.debug("Ignoring MSP packet with unknown function")

    def _send(self) -> None:
        """
        Forwards packets from the queue to the browser
        """
        while self._connected:
            packet: MSPPacket = self._send_queue.get()
            web_bridge.broadcast(bytes(packet.get_packet()))

    def disconnect(self):
        self._connected = False
        self._buffer.clear()

        if self._send_greenlet is not None:
            self._send_greenlet.kill()

        if web_bridge.connection is self:
            web_bridge.connection = None


class ConnectionTypeEnum(ConnectionType, Enum):
    """
    Enum for different connection selections
    """

    USB = SerialConnection, 1
    ONBOARD = SerialConnection, 2
    SOCKET = SocketConnection, 3
    WEB = WebConnection, 4
