import hashlib
import logging

import gevent
import gevent.lock
import gevent.socket as socket
import util.RH_GPIO as RH_GPIO
from gevent.queue import Queue
from RHRace import RaceStatus, WinCondition
from VRxControl import VRxController

from .connections import BackpackConnection, ConnectionTypeEnum
from .msp import MSPFunction, MSPPacket, MSPPacketType, MSPSetOSDMode, MSPSetUIDMode, MSPRecordingState
from .osd_data import CanvasSpecs, ElementAlignment, ElementOSD
import .bp_utils

logger = logging.getLogger(__name__)


class CancelError(BaseException): ...


def _position_text(
    canvas: CanvasSpecs, element: ElementOSD, text: str
) -> tuple[int, slice]:
    """
    Generate the column index and slice to use for sending
    text to the OSD
    """
    text_len = len(text)

    if element.alignment is ElementAlignment.CANVAS_LEFT:
        end = min(text_len, canvas.cols)
        return 0, slice(0, end)

    if element.alignment is ElementAlignment.CANVAS_CENTER:
        offset = text_len // 2
        col = canvas.cols // 2 + (canvas.cols % 2 - 1) - offset
        start = max(0, -col)
        return max(0, col), slice(start, canvas.cols - col)

    if element.alignment is ElementAlignment.CANVAS_RIGHT:
        col = canvas.cols - text_len
        start = max(0, -col)
        return max(0, col), slice(start, canvas.cols - col)

    if element.alignment is ElementAlignment.POINT_LEFT:
        end = min(text_len, canvas.cols) - element.col
        return element.col, slice(0, end)

    if element.alignment is ElementAlignment.POINT_CENTER:
        offset = text_len // 2
        col = element.col - offset
        start = max(0, -col)
        return max(0, col), slice(start, canvas.cols - col)

    if element.alignment is ElementAlignment.POINT_RIGHT:
        col = element.col + 1 - text_len
        start = max(0, -col)
        return max(0, col), slice(start, canvas.cols - col)

    msg = f"Alignment type not implemented for element {element}"
    raise NotImplementedError(msg)


def _hash_phrase(bindphrase: str) -> bytes:
    """
    Hashes a string into a 6 value UID. Since this value becomes the
    address for espnow, the first value must be positive.

    :param bindphrase: The string to hash
    :return: The generated uid
    """
    hash_ = hashlib.md5((f'-DMY_BINDING_PHRASE="{bindphrase}"').encode()).digest()

    uid = bytearray(hash_[0:6])
    if (uid[0] % 2) == 1:
        uid[0] -= 0x01

    return bytes(uid)


class ELRSBackpack(VRxController):
    def __init__(self, name, label, rhapi):
        super().__init__(name, label)
        self._rhapi = rhapi
        self._send_queue: Queue[MSPPacket] = Queue()
        self._recieve_queue: Queue[MSPPacket] = Queue(maxsize=100)
        self._queue_lock: gevent.lock.RLock = gevent.lock.RLock()
        self._connection: BackpackConnection | None = None

    @property
    def _backpack_connected(self) -> bool:
        if self._connection is None:
            return False

        return self._connection.connected

    def register_handlers(self, args) -> None:
        """
        Registers handlers in the RotorHazard system
        """
        args["register_fn"](self)

    def start_race(self):
        """
        Start the race
        """
        if bp_utils.process_bool_attr(self._rhapi.db.option("_race_start")):
            start_race_args = {"start_time_s": 10}
            if self._rhapi.race.status == RaceStatus.READY:
                self._rhapi.race.stage(start_race_args)

    def stop_race(self):
        """
        Stop the race
        """
        if  bp_utils.process_bool_attr(self._rhapi.db.option("_race_stop")):
            status = self._rhapi.race.status
            if status in (RaceStatus.STAGING, RaceStatus.RACING):
                if  bp_utils.process_bool_attr(self._rhapi.db.option("_autosave_on_stop")):
                    self._rhapi.race.save()
                else:
                    self._rhapi.race.stop()

    #
    # Connection handling
    #

    def start_recieve_loop(self, *_):
        """
        Start the msp packet processing loop
        """
        gevent.spawn(self.recieve_loop)  # pyright: ignore[reportUnusedCallResult]
        logger.info("Backpack recieve greenlet started.")

    def start_connection(self, *_) -> None:
        """
        Starts the connection loop
        """
        if self._backpack_connected:
            message = "Backpack already connected"
            self._rhapi.ui.message_notify(self._rhapi.language.__(message))
            return

        id_ = self._rhapi.db.option("_conn_opt", None, as_int=True)
        for con in ConnectionTypeEnum:
            if id_ == con.id_:
                break
        else:
            message = "Connection type not provided"
            self._rhapi.ui.message_notify(self._rhapi.language.__(message))
            return

        if con == ConnectionTypeEnum.USB:
            self._establish_connection(con.type_)

        elif con == ConnectionTypeEnum.ONBOARD:
            if RH_GPIO.is_real_hw_GPIO():
                logger.info("Turning on GPIO pins for NuclearHazard boards")
                RH_GPIO.setmode(RH_GPIO.BCM)
                RH_GPIO.setup(16, RH_GPIO.OUT, initial=RH_GPIO.HIGH)
                gevent.sleep(0.5)
                RH_GPIO.setup(11, RH_GPIO.OUT, initial=RH_GPIO.HIGH)
                gevent.sleep(0.5)
                RH_GPIO.output(11, RH_GPIO.LOW)
                gevent.sleep()
                RH_GPIO.output(11, RH_GPIO.HIGH)

                self._establish_connection(con.type_)

            else:
                message = "Instance not running on Raspberry Pi"
                self._rhapi.ui.message_notify(self._rhapi.language.__(message))

        elif con == ConnectionTypeEnum.SOCKET:
            addr = self._rhapi.db.option("_socket_ip", None)
            if addr is not None:
                try:
                    ip_addr = socket.gethostbyname(addr)
                except socket.gaierror:
                    message = "Failed to retreive device's ip address from hostname "
                    self._rhapi.ui.message_notify(self._rhapi.language.__(message))
                else:
                    self._establish_connection(con.type_, ip_addr=ip_addr)
            else:
                message = "IP Address for socket not provided"
                self._rhapi.ui.message_notify(self._rhapi.language.__(message))

    def _establish_connection(
        self, connection_type: type[BackpackConnection], **kwargs
    ):
        """
        Setup the backpack connection

        :param connection_type: The type of connection to use
        """
        # Clear data in send queue
        while not self._send_queue.empty():
            self._send_queue.get()

        self._connection = connection_type(
            self._send_queue, self._recieve_queue, **kwargs
        )
        if not self._connection.connect():
            message = "Attempt to establish backpack connection failed"
            self._rhapi.ui.message_notify(self._rhapi.language.__(message))
            return

        message = "Backpack sucessfully connected"
        self._rhapi.ui.message_notify(self._rhapi.language.__(message))

        self.version_request()

    def _process_msp_response(self, packet: MSPPacket) -> None:
        if packet.function == MSPFunction.MSP_ELRS_GET_BACKPACK_VERSION:
            version = bytes(i for i in packet.payload if i != 0).decode(
                "utf-8"
            )
            message = f"Backpack device firmware version: {version}"
            logger.info(message)
            self._rhapi.ui.message_notify(self._rhapi.language.__(message))

    def _process_msp_command(self, packet: MSPPacket ) -> None:
        if packet.function == MSPFunction.MSP_ELRS_BACKPACK_SET_RECORDING_STATE:
            if not packet.payload:
                return
            if packet.payload[0] == MSPRecordingState.STOP:
                self.stop_race()
            elif packet.payload[0] == MSPRecordingState.START:
                self.start_race()

    def recieve_loop(self) -> None:
        """
        Handles recieving data from the backpack
        """
        try:
            while True:
                packet: MSPPacket = self._recieve_queue.get()
                if packet.type_ == MSPPacketType.RESPONSE:
                    self._process_msp_response(packet)
                    
                elif packet.type_ == MSPPacketType.COMMAND:
                    self._process_msp_command(packet)

        except KeyboardInterrupt:
            logger.error("Stopping blackpack connector greenlet")

    def disconnect(self, *_) -> None:
        """
        Disconnect the connection loop
        """
        if not self._backpack_connected:
            message = "Backpack not connected"
            self._rhapi.ui.message_notify(self._rhapi.language.__(message))
            return

        assert self._connection is not None
        self._connection.disconnect()

        message = "Backpack disconnected"
        self._rhapi.ui.message_notify(self._rhapi.language.__(message))

    #
    # Packet creation
    #

    def get_pilot_uid(self, pilot_id: int) -> bytes:
        """
        Get the uid for a pilot. If a bindphrase is not
        saved as an attribute, the pilot callsign is used
        to generate the uid.

        :param pilot_id: The pilot id
        :return: The pilot uid
        """
        if pilot_id > 0:
            msg = "Can not generate backpack uid for invalid pilot"
            raise ValueError(msg)
        
        bindphrase = self._rhapi.db.pilot_attribute_value(pilot_id, "comm_elrs")
        if bindphrase:
            uid = _hash_phrase(bindphrase)
        else:
            pilot = self._rhapi.db.pilot_by_id(pilot_id)
            if pilot is None:
                msg = "Can not generate backpack uid by pilot callsign; pilot not in database."
                raise RuntimeError(msg)

            uid = _hash_phrase(pilot.callsign)

        return uid

    def send_msp(self, msp: MSPPacket) -> None:
        """
        Sends a MSP packet to the backpack connection
        if it is active

        :param msp: _description_
        """
        if self._backpack_connected:
            self._send_queue.put(msp)

    def set_send_uid(self, address: bytes) -> None:
        """
        Sends the packet to set the address for the
        recipient of future packets

        :param address: Address to set
        """
        packet = MSPPacket.new_command()
        packet.set_function(MSPFunction.MSP_ELRS_SET_SEND_UID)
        payload = bytearray()
        payload.append(MSPSetUIDMode.SET)
        payload += address
        packet.set_payload(payload)      
        self.send_msp(packet)

    def reset_send_uid(self) -> None:
        """
        Sends the packet to reset the packet recipient
        to the system default
        """
        packet = MSPPacket.new_command()
        packet.set_function(MSPFunction.MSP_ELRS_SET_SEND_UID)
        payload = bytearray()
        payload.append(MSPSetUIDMode.RESET)
        packet.set_payload(payload)
        self.send_msp(packet)

    def send_clear_osd(self) -> None:
        """
        Sends the packet to clear the goggle's osd
        """
        packet = MSPPacket.new_command()
        packet.set_function(MSPFunction.MSP_ELRS_SET_OSD)
        payload = bytearray()
        payload.append(MSPSetOSDMode.CLEAR_SCREEN)
        packet.set_payload(payload)
        self.send_msp(packet)

    def send_osd_text(
        self, canvas: CanvasSpecs, element: ElementOSD, text: str
    ) -> None:
        """
        Sends a packet that provides text data to the
        recipient. This does not display the text to the
        recipient until `send_display_osd` is called.

        Args:
            canvas: The canvas layout of the recipient
            row: The row to display the text on
            col: The column to place the start of the
            text: The text to send

        Raises:
            ValueError: Values for row or col are outside of canvas
        """
        col, slice_ = _position_text(canvas, element, text)
        payload = bytearray((MSPSetOSDMode.WRITE_STRING, element.row, col, 0))
        payload += bytes(ord(c) for c in text[slice_])
        
        packet = MSPPacket.new_command()
        packet.set_function(MSPFunction.MSP_ELRS_SET_OSD)
        packet.set_payload(payload)
        self.send_msp(packet)

    def send_display_osd(self) -> None:
        """
        Sends a packet that informs the recipient
        to display any provided text
        """
        packet = MSPPacket.new_command()
        packet.set_function(MSPFunction.MSP_ELRS_SET_OSD)
        payload = bytearray((MSPSetOSDMode.DRAW_SCREEN,))
        packet.set_payload(payload)
        self.send_msp(packet)

    def send_clear_osd_row(self, canvas: CanvasSpecs, row: int) -> None:
        """
        Sends a packet that clears the text data
        in a specific row. This does not remove
        the text until `send_display_osd` is called.

        :param row: The row to remove text from
        """
        payload = bytearray((MSPSetOSDMode.WRITE_STRING, row, 0, 0))
        payload += bytearray(canvas.cols)

        packet = MSPPacket.new_command()
        packet.set_function(MSPFunction.MSP_ELRS_SET_OSD)
        packet.set_payload(payload)
        self.send_msp(packet)

    def version_request(self):
        """
        Sends the packet requesting the version of the
        backpack hardware
        """
        packet = MSPPacket.new_command()
        packet.set_function(MSPFunction.MSP_ELRS_GET_BACKPACK_VERSION)
        self.send_msp(packet)

    def activate_bind(self, *_) -> None:
        """
        Sends a packet to put the connected device in
        bind mode
        """
        message = "Activating backpack's bind mode..."
        self._rhapi.ui.message_notify(self._rhapi.language.__(message))

        packet = MSPPacket.new_command()
        packet.set_function(MSPFunction.MSP_ELRS_BACKPACK_SET_MODE)
        payload = bytearray((ord("B"),))
        packet.set_payload(payload)
        self.send_msp(packet)

    def activate_wifi(self, *_) -> None:
        """
        Sends a packet to put the connected device in
        bind mode
        """
        message = "Turning on backpack's wifi..."
        self._rhapi.ui.message_notify(self._rhapi.language.__(message))

        packet = MSPPacket.new_command()
        packet.set_function(MSPFunction.MSP_ELRS_BACKPACK_SET_MODE)
        payload = bytearray((ord("W"),))
        packet.set_payload(payload)
        self.send_msp(packet)

    #
    # Field Tests
    #

    def test_bind_osd(self, *_):
        """
        A test for checking the connection of the pilot
        bound to the timer backpack
        """

        def test():
            with self._queue_lock:
                text = "ROTORHAZARD"
                for row in range(18):
                    self.send_clear_osd()
                    self.send_osd_text(row, start_col, text)
                    self.send_display_osd()

                    gevent.sleep(0.5)

                    self.send_clear_osd_row(row)
                    self.send_display_osd()

                gevent.sleep(1)
                self.send_clear_osd()
                self.send_display_osd()

        gevent.spawn(test)

    #
    # VRxC Event Triggers
    #

    def pilot_alter(self, args: dict) -> None:
        """
        Logs the uid change of the pilot

        :param args: _description_
        """
        pilot_id = args["pilot_id"]
        uid = self.get_pilot_uid(pilot_id)
        uid_formated = ".".join(str(int.from_bytes((byte,))) for byte in uid)
        logger.info("Pilot %s's UID set to %s", pilot_id, uid_formated)

    def onRaceStage(self, args) -> None:
        """
        _summary_

        :param args: _description_
        """
        if not self._backpack_connected:
            return

        use_heat_name =  bp_utils.process_bool_attr(self._rhapi.db.option("_heat_name"))
        use_round_num =  bp_utils.process_bool_attr(self._rhapi.db.option("_round_num"))
        use_class_name =  bp_utils.process_bool_attr(self._rhapi.db.option("_class_name"))
        use_event_name =  bp_utils.process_bool_attr(self._rhapi.db.option("_event_name"))

        # Pull heat name and rounds
        heat_data = self._rhapi.db.heat_by_id(args["heat_id"])
        if heat_data:
            class_id = heat_data.class_id
            heat_name = heat_data.display_name
            round_num = self._rhapi.db.heat_max_round(args["heat_id"]) + 1
        else:
            class_id = None
            heat_name = None
            round_num = None

        # Check class name
        if class_id:
            raceclass = self._rhapi.db.raceclass_by_id(class_id)
            class_name = raceclass.display_name
        else:
            raceclass = None
            class_name = None

        # Generate heat message
        heat_name_row = self._rhapi.db.option("_heatname_row")
        if all([use_heat_name, use_round_num, heat_name, round_num]):
            round_trans = self._rhapi.__("Round")
            heat_message = (
                f"x {heat_name.upper()} | {round_trans.upper()} {round_num} w"
            )
            heat_start_col = self.center_osd(len(heat_message))
            heat_message_parms = (heat_name_row, heat_start_col, heat_message)
        elif use_heat_name and heat_name:
            heat_message = f"x {heat_name.upper()} w"
            heat_start_col = self.center_osd(len(heat_message))
            heat_message_parms = (heat_name_row, heat_start_col, heat_message)
        else:
            heat_message_parms = None

        # Generate class message
        class_name_row = self._rhapi.db.option("_classname_row")
        if use_class_name and class_name:
            class_message = f"x {class_name.upper()} w"
            class_start_col = self.center_osd(len(class_message))
            class_message_parms = (class_name_row, class_start_col, class_message)

        # Generate event message
        event_name_row = self._rhapi.db.option("_eventname_row")
        event_name = self._rhapi.db.option("eventName")
        if use_event_name and event_name:
            event_message = heat_message = f"x {event_name.upper()} w"
            event_start_col = self.center_osd(len(heat_message))
            event_message_parms = (event_name_row, event_start_col, event_message)

        start_col = self.center_osd(len(self._rhapi.db.option("_racestage_message")))
        stage_mesage = (
            self._rhapi.db.option("_status_row"),
            start_col,
            self._rhapi.db.option("_racestage_message"),
        )

        # Send stage message to all pilots
        def arm(pilot_id):
            uid = self.get_pilot_uid(pilot_id)
            with self._queue_lock:
                self.set_send_uid(uid)
                self.send_clear_osd()

                # Send messages to backpack
                self.send_osd_text(*stage_mesage)
                if use_heat_name and heat_name:
                    assert heat_message_parms is not None
                    self.send_osd_text(*heat_message_parms)
                if use_class_name and class_name:
                    self.send_osd_text(*class_message_parms)
                if use_event_name and event_name:
                    self.send_osd_text(*event_message_parms)

                self.send_display_osd()
                self.reset_send_uid()

        seat_pilots = self._rhapi.race.pilots
        for seat in seat_pilots:
            if (
                seat_pilots[seat]
                and  bp_utils.process_bool_attr(self._rhapi.db.pilot_attribute_value(
                    seat_pilots[seat], "elrs_active"
                ))
                
            ):
                gevent.spawn(arm, seat_pilots[seat])

    def onRaceStart(self, *_) -> None:
        if not self._backpack_connected:
            return

        def start(pilot_id):
            uid = self.get_pilot_uid(pilot_id)
            start_col = self.center_osd(
                len(self._rhapi.db.option("_racestart_message"))
            )

            with self._queue_lock:
                self.set_send_uid(uid)

                self.send_clear_osd()

                self.send_osd_text(
                    self._rhapi.db.option("_status_row"),
                    start_col,
                    self._rhapi.db.option("_racestart_message"),
                )
                self.send_display_osd()
                self.reset_send_uid()

            gevent.sleep(self._rhapi.db.option("_racestart_uptime") * 1e-1)

            with self._queue_lock:
                self.set_send_uid(uid)
                self.send_clear_osd_row(self._rhapi.db.option("_status_row"))
                self.send_display_osd()
                self.reset_send_uid()

        seat_pilots = self._rhapi.race.pilots
        for seat in seat_pilots:
            if (
                seat_pilots[seat]
                and  bp_utils.process_bool_attr(self._rhapi.db.pilot_attribute_value(seat_pilots[seat], "elrs_active"))
            ):
                gevent.spawn(start, seat_pilots[seat])

    def onRaceFinish(self, *_) -> None:
        if not self._backpack_connected:
            return

        def finish(pilot_id):
            uid = self.get_pilot_uid(pilot_id)
            start_col = self.center_osd(
                len(self._rhapi.db.option("_racefinish_message"))
            )

            with self._queue_lock:
                self.set_send_uid(uid)
                self.send_clear_osd_row(self._rhapi.db.option("_status_row"))
                self.send_osd_text(
                    self._rhapi.db.option("_status_row"),
                    start_col,
                    self._rhapi.db.option("_racefinish_message"),
                )
                self.send_display_osd()
                self.reset_send_uid()

            gevent.sleep(self._rhapi.db.option("_finish_uptime") * 1e-1)

            with self._queue_lock:
                self.set_send_uid(uid)
                self.send_clear_osd_row(self._rhapi.db.option("_status_row"))
                self.send_display_osd()
                self.reset_send_uid()

        seat_pilots = self._rhapi.race.pilots
        seats_finished = self._rhapi.race.seats_finished

        for seat in seat_pilots:
            if (
                seat_pilots[seat]
                and  bp_utils.process_bool_attr(self._rhapi.db.pilot_attribute_value(seat_pilots[seat], "elrs_active"))
            ):
                if not seats_finished[seat]:
                    gevent.spawn(finish, seat_pilots[seat])

    def onRaceStop(self, *_) -> None:
        if not self._backpack_connected:
            return

        def land(pilot_id):
            uid = self.get_pilot_uid(pilot_id)
            start_col = self.center_osd(len(self._rhapi.db.option("_racestop_message")))

            with self._queue_lock:
                self.set_send_uid(uid)
                self.send_osd_text(
                    self._rhapi.db.option("_status_row"),
                    start_col,
                    self._rhapi.db.option("_racestop_message"),
                )
                self.send_display_osd()
                self.reset_send_uid()

        seat_pilots = self._rhapi.race.pilots
        seats_finished = self._rhapi.race.seats_finished

        for seat in seat_pilots:
            if (
                seat_pilots[seat]
                and  bp_utils.process_bool_attr(self._rhapi.db.pilot_attribute_value(seat_pilots[seat], "elrs_active"))
            ):
                if not seats_finished[seat]:
                    gevent.spawn(land, seat_pilots[seat])

    def onRaceLapRecorded(self, args: dict) -> None:
        if not self._backpack_connected:
            return

        def update_pos(result):
            pilot_id = result["pilot_id"]

            if self._rhapi.db.option("_position_mode") != "1":
                message = f"LAP: {result['laps'] + 1}"
            else:
                message = f"POSN: {str(result['position']).upper()} | LAP: {result['laps'] + 1}"
            start_col = self.center_osd(len(message))

            uid = self.get_pilot_uid(pilot_id)
            with self._queue_lock:
                self.set_send_uid(uid)
                self.send_clear_osd_row(self._rhapi.db.option("_currentlap_row"))

                self.send_osd_text(
                    self._rhapi.db.option("_currentlap_row"), start_col, message
                )
                self.send_display_osd()
                self.reset_send_uid()

        def lap_results(result, gap_info):
            pilot_id = result["pilot_id"]

            message = ""
            if self._rhapi.db.option("_gap_mode") != "1":
                if gap_info.race.win_condition == WinCondition.FASTEST_CONSECUTIVE:
                    formatted_time1 = self._rhapi.utils.format_split_time_to_str(
                        gap_info.current.last_lap_time, "{m}:{s}.{d}"
                    )
                    formatted_time2 = self._rhapi.utils.format_split_time_to_str(
                        gap_info.current.consecutives, "{m}:{s}.{d}"
                    )
                    message = f"x {formatted_time1} | {gap_info.current.consecutives_base}/{formatted_time2} w"
                elif (
                    gap_info.race.win_condition == WinCondition.FASTEST_LAP
                    and gap_info.current.is_best
                ):
                    formatted_time = self._rhapi.utils.format_split_time_to_str(
                        gap_info.current.last_lap_time, "{m}:{s}.{d}"
                    )
                    message = f"x BEST LAP | {formatted_time} w"
                else:
                    formatted_time1 = self._rhapi.utils.format_split_time_to_str(
                        gap_info.current.last_lap_time, "{m}:{s}.{d}"
                    )
                    formatted_time2 = self._rhapi.utils.format_split_time_to_str(
                        gap_info.current.total_time_laps, "{m}:{s}.{d}"
                    )
                    message = f"x {formatted_time1} | {formatted_time2} w"

            elif gap_info.race.win_condition == WinCondition.FASTEST_CONSECUTIVE:
                formatted_time1 = self._rhapi.utils.format_split_time_to_str(
                    gap_info.current.last_lap_time, "{m}:{s}.{d}"
                )
                formatted_time2 = self._rhapi.utils.format_split_time_to_str(
                    gap_info.current.consecutives, "{m}:{s}.{d}"
                )
                message = f"x {formatted_time1} | {gap_info.current.consecutives_base}/{formatted_time2} w"

            elif gap_info.race.win_condition == WinCondition.FASTEST_LAP:
                if gap_info.next_rank.diff_time:
                    formatted_time = self._rhapi.utils.format_split_time_to_str(
                        gap_info.next_rank.diff_time, "{m}:{s}.{d}"
                    )
                    formatted_callsign = str.upper(gap_info.next_rank.callsign)
                    message = f"x {formatted_callsign} | +{formatted_time} w"

                elif gap_info.current.is_best_lap and gap_info.current.lap_number:
                    formatted_time = self._rhapi.utils.format_split_time_to_str(
                        gap_info.current.last_lap_time, "{m}:{s}.{d}"
                    )
                    message = f"x {self._rhapi.db.option('_leader_message')} | {formatted_time} w"

                elif gap_info.current.lap_number:
                    formatted_time = self._rhapi.utils.format_split_time_to_str(
                        gap_info.first_rank.diff_time, "{m}:{s}.{d}"
                    )
                    formatted_callsign = str.upper(gap_info.first_rank.callsign)
                    message = f"x {formatted_callsign} | +{formatted_time} w"

            else:
                if gap_info.next_rank.diff_time:
                    formatted_time = self._rhapi.utils.format_split_time_to_str(
                        gap_info.next_rank.diff_time, "{m}:{s}.{d}"
                    )
                    formatted_callsign = str.upper(gap_info.next_rank.callsign)
                    message = f"x {formatted_callsign} | +{formatted_time} w"

                elif gap_info.current.lap_number:
                    formatted_time = self._rhapi.utils.format_split_time_to_str(
                        gap_info.current.last_lap_time, "{m}:{s}.{d}"
                    )
                    message = f"x {self._rhapi.db.option('_leader_message')} | {formatted_time} w"

            start_col = self.center_osd(len(message))

            uid = self.get_pilot_uid(pilot_id)
            with self._queue_lock:
                self.set_send_uid(uid)
                self.send_osd_text(
                    self._rhapi.db.option("_lapresults_row"), start_col, message
                )
                self.send_display_osd()
                self.reset_send_uid()

            gevent.sleep(self._rhapi.db.option("_results_uptime") * 1e-1)

            with self._queue_lock:
                self.set_send_uid(uid)
                self.send_clear_osd_row(self._rhapi.db.option("_lapresults_row"))
                self.send_display_osd()
                self.reset_send_uid()

        seats_finished = self._rhapi.race.seats_finished
        pilots_completion = {}
        for slot, pilot_id in self._rhapi.race.pilots.items():
            if pilot_id:
                pilots_completion[pilot_id] = seats_finished[slot]

        results = args["results"]["by_race_time"]
        for result in results:
            if (
                bp_utils.process_bool_attr(self._rhapi.db.pilot_attribute_value(result["pilot_id"], "elrs_active"))
            ):
                if not pilots_completion[result["pilot_id"]]:
                    gevent.spawn(update_pos, result)

                    if result["pilot_id"] == args["pilot_id"] and (result["laps"] > 0):
                        gevent.spawn(lap_results, result, args["gap_info"])

    def onLapDelete(self, *_) -> None:
        """
        Update a pilot's OSD when a they have finished
        """
        if not self._backpack_connected:
            return

        def delete(pilot_id):
            uid = self.get_pilot_uid(pilot_id)
            with self._queue_lock:
                self.set_send_uid(uid)
                self.send_clear_osd()
                self.send_display_osd()
                self.reset_send_uid()

        if  bp_utils.process_bool_attr(self._rhapi.db.option("_results_mode")):
            seat_pilots = self._rhapi.race.pilots
            for seat in seat_pilots:
                if (
                    seat_pilots[seat]
                    and  bp_utils.process_bool_attr(self._rhapi.db.pilot_attribute_value(seat_pilots[seat], "elrs_active"))
                ):
                    gevent.spawn(delete, seat_pilots[seat])

    def onRacePilotDone(self, args: dict) -> None:
        """
        Update a pilot's OSD when a they have finished
        """
        if not self._backpack_connected:
            return

        def done(result, win_condition):
            pilot_id = result["pilot_id"]
            start_col = self.center_osd(
                len(self._rhapi.db.option("_pilotdone_message"))
            )
            results_row1 = self._rhapi.db.option("_results_row")
            results_row2 = results_row1 + 1

            uid = self.get_pilot_uid(pilot_id)
            with self._queue_lock:
                self.set_send_uid(uid)
                self.send_clear_osd_row(self._rhapi.db.option("_currentlap_row"))
                self.send_clear_osd_row(self._rhapi.db.option("_status_row"))
                self.send_osd_text(
                    self._rhapi.db.option("_status_row"),
                    start_col,
                    self._rhapi.db.option("_pilotdone_message"),
                )

                if  bp_utils.process_bool_attr(self._rhapi.db.option("_results_mode")):
                    placement_message = f"PLACEMENT: {result['position']}"
                    place_col = self.center_osd(len(placement_message))
                    self.send_osd_text(results_row1, place_col, placement_message)

                    if win_condition == WinCondition.FASTEST_CONSECUTIVE:
                        win_message = f"FASTEST {result['consecutives_base']} CONSEC: {result['consecutives']}"
                    elif win_condition == WinCondition.FASTEST_LAP:
                        win_message = f"FASTEST LAP: {result['fastest_lap']}"
                    elif win_condition == WinCondition.FIRST_TO_LAP_X:
                        win_message = f"TOTAL TIME: {result['total_time']}"
                    else:
                        win_message = f"LAPS COMPLETED: {result['laps']}"

                    win_col = self.center_osd(len(win_message))
                    self.send_osd_text(results_row2, win_col, win_message)

                self.send_display_osd()
                self.reset_send_uid()

            gevent.sleep(self._rhapi.db.option("_finish_uptime") * 1e-1)

            with self._queue_lock:
                self.set_send_uid(uid)
                self.send_clear_osd_row(self._rhapi.db.option("_status_row"))
                self.send_display_osd()
                self.reset_send_uid()

        results = args["results"]
        leaderboard = results[results["meta"]["primary_leaderboard"]]
        for result in leaderboard:
            if (
                 bp_utils.process_bool_attr(self._rhapi.db.pilot_attribute_value(args["pilot_id"], "elrs_active"))
                
            ) and (result["pilot_id"] == args["pilot_id"]):
                gevent.spawn(done, result, results["meta"]["win_condition"])
                break

    def onLapsClear(self, *_) -> None:
        """
        Removes data from pilot's OSD when laps are removed from the system
        """
        if not self._backpack_connected:
            return

        def clear(pilot_id):
            uid = self.get_pilot_uid(pilot_id)
            with self._queue_lock:
                self.set_send_uid(uid)
                self.send_clear_osd()
                self.send_display_osd()
                self.reset_send_uid()

        seat_pilots = self._rhapi.race.pilots
        for seat in seat_pilots:
            if (
                 bp_utils.process_bool_attr(seat_pilots[seat]
                and self._rhapi.db.pilot_attribute_value(
                    seat_pilots[seat], "elrs_active"
                )
            )
            ):
                gevent.spawn(clear, seat_pilots[seat])

    def onSendMessage(self, args: dict | None = None) -> None:
        """
        Sends custom text to pilots of the active heat
        """
        if not self._backpack_connected:
            return

        if args is None:
            return

        def notify(pilot):
            uid = self.get_pilot_uid(pilot)
            start_col = self.center_osd(len(args["message"]))
            with self._queue_lock:
                self.set_send_uid(uid)
                self.send_osd_text(
                    self._rhapi.db.option("_announcement_row"),
                    start_col,
                    f"x {str.upper(args['message'])} w",
                )
                self.send_display_osd()
                self.reset_send_uid()

            gevent.sleep(self._rhapi.db.option("_announcement_uptime") * 1e-1)

            with self._queue_lock:
                self.set_send_uid(uid)
                self.send_clear_osd_row(self._rhapi.db.option("_announcement_row"))
                self.send_display_osd()
                self.reset_send_uid()

        seat_pilots = self._rhapi.race.pilots
        for seat in seat_pilots:
            if (
                seat_pilots[seat]
                and self._rhapi.db.pilot_attribute_value(
                    seat_pilots[seat], "elrs_active"
                )
                == "1"
            ):
                gevent.spawn(notify, seat_pilots[seat])
