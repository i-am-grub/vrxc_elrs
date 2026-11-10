import logging

import RHAPI
from eventmanager import Evt
from RHUI import UIField, UIFieldSelectOption, UIFieldType

from .connections import ConnectionTypeEnum
from .elrs_backpack import ELRSBackpack

logger = logging.getLogger(__name__)


def initialize(rhapi: RHAPI.RHAPI):

    controller = ELRSBackpack("elrs", "ELRS", rhapi)

    rhapi.events.on(Evt.VRX_INITIALIZE, controller.register_handlers)
    rhapi.events.on(Evt.PILOT_ALTER, controller.pilot_alter)
    rhapi.events.on(
        Evt.STARTUP, controller.start_recieve_loop, name="start_recieve_loop"
    )
    rhapi.events.on(Evt.STARTUP, controller.start_connection, name="start_connection")

    #
    # Setup UI
    #

    elrs_bindphrase = UIField(
        name="comm_elrs", label="ELRS BP Bind Phrase", field_type=UIFieldType.TEXT
    )
    rhapi.fields.register_pilot_attribute(elrs_bindphrase)

    active = UIField("elrs_active", "Enable ELRS OSD", field_type=UIFieldType.CHECKBOX)
    rhapi.fields.register_pilot_attribute(active)

    rhapi.ui.register_panel(
        "elrs_settings", "ELRS Backpack General Settings", "settings", order=0
    )

    rhapi.ui.register_panel(
        "elrs_vrxc", "ELRS Backpack OSD Settings", "settings", order=0
    )

    #
    # Check Boxes
    #

    _race_start = UIField(
        "_race_start",
        "Start Race from Transmitter",
        desc="Allows the race director to remotely start races",
        field_type=UIFieldType.CHECKBOX,
    )
    rhapi.fields.register_option(_race_start, "elrs_settings")

    _race_stop = UIField(
        "_race_stop",
        "Stop Race from Transmitter",
        desc="Allows the race director to remotely stop races",
        field_type=UIFieldType.CHECKBOX,
    )
    rhapi.fields.register_option(_race_stop, "elrs_settings")

    _autosave_on_stop = UIField(
        "_autosave_on_stop",
        "Autosave on stop",
        desc="Automatically save the race when stopping from the transmitter",
        field_type=UIFieldType.CHECKBOX,
        value="0",
    )
    rhapi.fields.register_option(_autosave_on_stop, "elrs_settings")

    _vtx_mode = UIField(
        "_vtx_mode",
        "Backpack Channel Mode",
        desc="Off - channels are not used. Backpack controls node - a channel change "
        "reported by the director's radio moves the node set below. RotorHazard sends "
        "to pilots - enables the buttons of the Run page. The two are exclusive.",
        field_type=UIFieldType.SELECT,
        options=[
            UIFieldSelectOption(value="0", label="Off"),
            UIFieldSelectOption(value="1", label="Backpack controls node"),
            UIFieldSelectOption(value="2", label="RotorHazard sends to pilots"),
        ],
        value="0",
    )
    rhapi.fields.register_option(_vtx_mode, "elrs_settings")

    _vtx_node = UIField(
        "_vtx_node",
        "Node Controlled by Backpack",
        desc="Used by the 'Backpack controls node' mode: node moved to the channel "
        "reported by the radio (MSP_SET_VTX_CONFIG). Ignored while a race is running.",
        field_type=UIFieldType.BASIC_INT,
        value=0,
    )
    rhapi.fields.register_option(_vtx_node, "elrs_settings")

    #
    # Send channels (Run page)
    #

    rhapi.ui.register_panel("elrs_channels", "ELRS Send Channels", "run", order=0)

    def refresh_pilot_options(*_, broadcast: bool = True) -> None:
        """
        Rebuilds the pilot list of the 'Send to pilot' selector
        """
        options = [UIFieldSelectOption(value=None, label="")]
        try:
            pilots = rhapi.db.pilots
        except Exception:  # database not ready while plugins load
            pilots = []

        for pilot in pilots:
            options.append(
                UIFieldSelectOption(value=str(pilot.id), label=pilot.display_callsign)
            )

        send_pilot = UIField(
            "_send_pilot",
            "Pilot",
            desc="Pilot to send the channel of their current or next heat to",
            field_type=UIFieldType.SELECT,
            options=options,
        )
        rhapi.fields.register_option(send_pilot, "elrs_channels")
        if broadcast:
            rhapi.ui.broadcast_ui("run")

    refresh_pilot_options(broadcast=False)
    for event in (Evt.STARTUP, Evt.PILOT_ADD, Evt.PILOT_ALTER, Evt.PILOT_DELETE):
        rhapi.events.on(event, refresh_pilot_options, name=f"elrs_pilots_{event}")

    rhapi.ui.register_quickbutton(
        "elrs_channels",
        "send_current",
        "Send to current pilots",
        controller.send_channels_current,
    )
    rhapi.ui.register_quickbutton(
        "elrs_channels",
        "send_all",
        "Send to all pilots",
        controller.send_channels_all,
    )
    rhapi.ui.register_quickbutton(
        "elrs_channels",
        "send_pilot",
        "Send to pilot",
        controller.send_channel_pilot,
    )

    _socket_ip = UIField(
        "_socket_ip",
        "ELRS Netpack Address",
        desc="Hostanme or IP Address of the ELRS Netpack",
        value="elrs-netpack.local",
        field_type=UIFieldType.TEXT,
    )
    rhapi.fields.register_option(_socket_ip, "elrs_settings")

    conn_opts = [UIFieldSelectOption(value=None, label="")]
    for type_ in ConnectionTypeEnum:
        race_selection = UIFieldSelectOption(value=type_.id_, label=type_.name)
        conn_opts.append(race_selection)

    _conn_opt = UIField(
        "_conn_opt",
        "Backback Connection Type",
        desc="Select the type of connection to use for the backpack",
        field_type=UIFieldType.SELECT,
        options=conn_opts,
    )
    rhapi.fields.register_option(_conn_opt, "elrs_settings")

    _heat_name = UIField(
        "_heat_name",
        "Show Heat Name",
        desc="Show the heat's name on start",
        field_type=UIFieldType.CHECKBOX,
    )
    rhapi.fields.register_option(_heat_name, "elrs_vrxc")

    _round_num = UIField(
        "_round_num",
        "Show Round Number",
        desc="Show round number on start",
        field_type=UIFieldType.CHECKBOX,
    )
    rhapi.fields.register_option(_round_num, "elrs_vrxc")

    _class_name = UIField(
        "_class_name",
        "Show Class Name",
        desc="Show the class's name on start",
        field_type=UIFieldType.CHECKBOX,
    )
    rhapi.fields.register_option(_class_name, "elrs_vrxc")

    _event_name = UIField(
        "_event_name",
        "Show Event Name",
        desc="Show the event's name on start",
        field_type=UIFieldType.CHECKBOX,
    )
    rhapi.fields.register_option(_event_name, "elrs_vrxc")

    _position_mode = UIField(
        "_position_mode",
        "Show Current Position and Lap",
        desc="off - only shows current lap",
        field_type=UIFieldType.CHECKBOX,
    )
    rhapi.fields.register_option(_position_mode, "elrs_vrxc")

    _gap_mode = UIField(
        "_gap_mode",
        "Show Gap Time",
        desc="off - shows lap time",
        field_type=UIFieldType.CHECKBOX,
    )
    rhapi.fields.register_option(_gap_mode, "elrs_vrxc")

    _results_mode = UIField(
        "_results_mode",
        "Show Post-Race Results",
        desc="Show pilot's results upon race completion",
        field_type=UIFieldType.CHECKBOX,
    )
    rhapi.fields.register_option(_results_mode, "elrs_vrxc")

    #
    # Text Fields
    #

    _racestage_message = UIField(
        "_racestage_message",
        "Race Stage Message",
        desc="lowercase letters are symbols",
        field_type=UIFieldType.TEXT,
        value="w ARM NOW x",
    )
    rhapi.fields.register_option(_racestage_message, "elrs_vrxc")

    _racestart_message = UIField(
        "_racestart_message",
        "Race Start Message",
        desc="lowercase letters are symbols",
        field_type=UIFieldType.TEXT,
        value="w   GO!   x",
    )
    rhapi.fields.register_option(_racestart_message, "elrs_vrxc")

    _pilotdone_message = UIField(
        "_pilotdone_message",
        "Pilot Done Message",
        desc="lowercase letters are symbols",
        field_type=UIFieldType.TEXT,
        value="w FINISHED! x",
    )
    rhapi.fields.register_option(_pilotdone_message, "elrs_vrxc")

    _racefinish_message = UIField(
        "_racefinish_message",
        "Race Finish Message",
        desc="lowercase letters are symbols",
        field_type=UIFieldType.TEXT,
        value="w FINISH LAP! x",
    )
    rhapi.fields.register_option(_racefinish_message, "elrs_vrxc")

    _racestop_message = UIField(
        "_racestop_message",
        "Race Stop Message",
        desc="lowercase letters are symbols",
        field_type=UIFieldType.TEXT,
        value="w  LAND NOW!  x",
    )
    rhapi.fields.register_option(_racestop_message, "elrs_vrxc")

    _leader_message = UIField(
        "_leader_message",
        "Race Leader Message",
        desc="lowercase letters are symbols",
        field_type=UIFieldType.TEXT,
        value="RACE LEADER",
    )
    rhapi.fields.register_option(_leader_message, "elrs_vrxc")

    #
    # Basic Integers
    #

    _racestart_uptime = UIField(
        "_racestart_uptime",
        "Start Message Uptime",
        desc="decaseconds",
        field_type=UIFieldType.BASIC_INT,
        value=5,
    )
    rhapi.fields.register_option(_racestart_uptime, "elrs_vrxc")

    _finish_uptime = UIField(
        "_finish_uptime",
        "Finish Message Uptime",
        desc="decaseconds",
        field_type=UIFieldType.BASIC_INT,
        value=20,
    )
    rhapi.fields.register_option(_finish_uptime, "elrs_vrxc")

    _results_uptime = UIField(
        "_results_uptime",
        "Lap Result Uptime",
        desc="decaseconds",
        field_type=UIFieldType.BASIC_INT,
        value=40,
    )
    rhapi.fields.register_option(_results_uptime, "elrs_vrxc")

    _announcement_uptime = UIField(
        "_announcement_uptime",
        "Announcement Uptime",
        desc="decaseconds",
        field_type=UIFieldType.BASIC_INT,
        value=50,
    )
    rhapi.fields.register_option(_announcement_uptime, "elrs_vrxc")

    _heatname_row = UIField(
        "_heatname_row",
        "Heat Name Row",
        desc="Use rows between 0-17",
        field_type=UIFieldType.BASIC_INT,
        value=2,
    )
    rhapi.fields.register_option(_heatname_row, "elrs_vrxc")

    _classname_row = UIField(
        "_classname_row",
        "Class Name Row",
        desc="Use rows between 0-17",
        field_type=UIFieldType.BASIC_INT,
        value=1,
    )
    rhapi.fields.register_option(_classname_row, "elrs_vrxc")

    _eventname_row = UIField(
        "_eventname_row",
        "Event Name Row",
        desc="Use rows between 0-17",
        field_type=UIFieldType.BASIC_INT,
        value=0,
    )
    rhapi.fields.register_option(_eventname_row, "elrs_vrxc")

    _announcement_row = UIField(
        "_announcement_row",
        "Announcement Row",
        desc="Use rows between 0-17",
        field_type=UIFieldType.BASIC_INT,
        value=3,
    )
    rhapi.fields.register_option(_announcement_row, "elrs_vrxc")

    _status_row = UIField(
        "_status_row",
        "Race Status Row",
        desc="Use rows between 0-17",
        field_type=UIFieldType.BASIC_INT,
        value=5,
    )
    rhapi.fields.register_option(_status_row, "elrs_vrxc")

    _currentlap_row = UIField(
        "_currentlap_row",
        "Current Lap/Position Row",
        desc="Use rows between 0-17",
        field_type=UIFieldType.BASIC_INT,
        value=0,
    )
    rhapi.fields.register_option(_currentlap_row, "elrs_vrxc")

    _lapresults_row = UIField(
        "_lapresults_row",
        "Lap/Gap Results Row",
        desc="Use rows between 0-17",
        field_type=UIFieldType.BASIC_INT,
        value=15,
    )
    rhapi.fields.register_option(_lapresults_row, "elrs_vrxc")

    _results_row = UIField(
        "_results_row",
        "Results Rows",
        desc="Use rows between 0-16. Uses two rows.",
        field_type=UIFieldType.BASIC_INT,
        value=13,
    )
    rhapi.fields.register_option(_results_row, "elrs_vrxc")

    #
    # Quick Buttons
    #

    rhapi.ui.register_quickbutton(
        "elrs_settings",
        "bp_connect",
        "Backpack Connect",
        controller.start_connection,
    )
    rhapi.ui.register_quickbutton(
        "elrs_settings",
        "bp_disconnect",
        "Backpack Disconnect",
        controller.disconnect,
    )
    rhapi.ui.register_quickbutton(
        "elrs_settings", "enable_bind", "Start Backpack Bind", controller.activate_bind
    )

    rhapi.ui.register_quickbutton(
        "elrs_settings",
        "test_osd",
        "Test Bound Backpack's OSD",
        controller.test_bind_osd,
    )
    rhapi.ui.register_quickbutton(
        "elrs_settings", "enable_wifi", "Start Backpack WiFi", controller.activate_wifi
    )
