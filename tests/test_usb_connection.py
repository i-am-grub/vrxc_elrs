"""Run with pytest, gevent and pyserial; no RotorHazard server or hardware needed."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from gevent.queue import Queue


DEVICE_PATH = "/dev/serial/by-path/platform-3f980000.usb-usb-0:1.1.3:1.0-port0"


@pytest.fixture(scope="module")
def plugin():
    # Stub the host APIs only; exercise the real plugin and MSP codec.
    class Controller:
        def __init__(self, *args):
            pass

    def field(name, label, field_type=None, **kwargs):
        return SimpleNamespace(name=name, label=label, field_type=field_type, **kwargs)

    gpio = Mock()
    with pytest.MonkeyPatch.context() as patch:
        modules = {
            "RHAPI": SimpleNamespace(RHAPI=object),
            "RHUI": SimpleNamespace(
                UIField=field,
                UIFieldSelectOption=SimpleNamespace,
                UIFieldType=SimpleNamespace(TEXT="text", CHECKBOX="checkbox",
                                            SELECT="select", BASIC_INT="basic_int"),
            ),
            "eventmanager": SimpleNamespace(Evt=SimpleNamespace(
                VRX_INITIALIZE="vrx", PILOT_ALTER="pilot", STARTUP="startup",
                OPTION_SET="optionSet")),
            "RHRace": SimpleNamespace(RaceStatus=Mock(), WinCondition=Mock()),
            "VRxControl": SimpleNamespace(VRxController=Controller),
            "util": SimpleNamespace(RH_GPIO=gpio),
            "util.RH_GPIO": gpio,
        }
        for name, module in modules.items():
            patch.setitem(sys.modules, name, module)
        path = Path(__file__).parents[1] / "custom_plugins/vrxc_elrs/__init__.py"
        spec = importlib.util.spec_from_file_location("usb_test_elrs", path)
        module = importlib.util.module_from_spec(spec)
        patch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        yield module


@pytest.fixture
def api():
    values = {}
    host = Mock()

    def option(name, default=None, as_int=False):
        value = values.get(name, default)
        return int(value) if as_int and value is not None else value

    host.db.option.side_effect = option
    host.language.__ = lambda message: message
    host.values = values
    return host


@pytest.fixture
def serial_env(plugin, monkeypatch):
    connections = sys.modules[plugin.__name__ + ".connections"]
    factory, scan, spawn = Mock(), Mock(return_value=[]), Mock()
    monkeypatch.setattr(connections.serial, "Serial", factory)
    monkeypatch.setattr(connections.serial.tools.list_ports, "comports", scan)
    monkeypatch.setattr(connections.gevent, "sleep", Mock())
    monkeypatch.setattr(connections.gevent, "spawn", spawn)
    packet = connections.MSPPacket()
    packet.set_type(connections.MSPPacketType.RESPONSE)
    packet.set_function(connections.MSPTypes.MSP_ELRS_GET_BACKPACK_VERSION)
    packet.set_payload(b"1.5.9")
    device = Mock()
    device.read_all.side_effect = [b"", packet.get_packet()]
    factory.return_value = device
    return SimpleNamespace(
        connection=connections.SerialConnection(Queue(), Queue()),
        factory=factory, scan=scan, spawn=spawn, device=device,
        module=connections,
    )


def test_explicit_path_bypasses_scan_and_requires_version_reply(serial_env):
    env = serial_env
    assert env.connection.connect(DEVICE_PATH)
    assert env.connection.connected
    assert env.factory.call_args.kwargs["port"] == DEVICE_PATH
    env.scan.assert_not_called()
    env.device.close.assert_not_called()
    assert env.spawn.call_count == 3


@pytest.mark.parametrize("path", [None, "", "   "])
def test_empty_path_autodetects_and_skips_reserved_ports(serial_env, path):
    env = serial_env
    env.scan.return_value = [SimpleNamespace(device=name) for name in
                             ["COM1", "/dev/ttyAMA0", "/dev/ttyAMA10", "/dev/ttyUSB1"]]
    assert env.connection.connect(path)
    env.scan.assert_called_once()
    env.factory.assert_called_once()
    assert env.factory.call_args.kwargs["port"] == "/dev/ttyUSB1"


def test_missing_explicit_path_does_not_fall_back_to_other_devices(serial_env):
    env = serial_env
    env.factory.side_effect = env.module.serial.SerialException("not present")
    assert not env.connection.connect(DEVICE_PATH)
    assert not env.connection.connected
    env.factory.assert_called_once()
    env.scan.assert_not_called()
    env.spawn.assert_not_called()


@pytest.mark.parametrize("response", [b"", b"Fusion ESP", b"not an MSP response"])
def test_wrong_device_is_closed_and_never_marked_connected(serial_env, response):
    env = serial_env
    env.device.read_all.side_effect = [b"", response]
    assert not env.connection.connect(DEVICE_PATH)
    assert not env.connection.connected
    env.device.close.assert_called_once()
    env.scan.assert_not_called()
    env.spawn.assert_not_called()


@pytest.mark.parametrize("stage", ["flush", "write", "reply"])
def test_serial_io_failure_closes_port(serial_env, stage):
    env = serial_env
    error = env.module.serial.SerialException("disconnected")
    if stage == "write":
        env.device.write.side_effect = error
    else:
        env.device.read_all.side_effect = [error] if stage == "flush" else [b"", error]
    assert not env.connection.connect(DEVICE_PATH)
    env.device.close.assert_called_once()
    env.spawn.assert_not_called()


def test_autodetection_releases_wrong_device_before_next_probe(serial_env):
    env = serial_env
    wrong = Mock()
    wrong.read_all.side_effect = [b"", b"Fusion ESP"]
    env.scan.return_value = [SimpleNamespace(device="/dev/ttyUSB0"),
                             SimpleNamespace(device="/dev/ttyUSB1")]

    def open_device(**kwargs):
        if kwargs["port"] == "/dev/ttyUSB0":
            return wrong
        wrong.close.assert_called_once()
        return env.device

    env.factory.side_effect = open_device
    assert env.connection.connect()
    assert env.factory.call_count == 2
    env.device.close.assert_not_called()


@pytest.mark.parametrize("selection", [None, "1", "2", "3"])
def test_path_visibility_on_load_and_when_selection_changes(plugin, api, selection):
    api.values.update(_conn_opt=selection, _serial_port=DEVICE_PATH)
    fields = {}
    api.fields.register_option.side_effect = lambda field, panel: fields.update(
        {field.name: (field, panel)})
    plugin.initialize(api)
    assert fields["_serial_port"][1] == ("elrs_settings" if selection == "1" else None)
    handler = next(call.args[1] for call in api.events.on.call_args_list
                   if call.args[0] == "optionSet")
    for value in ["1", "3", "2", "1"]:
        api.values["_conn_opt"] = value
        handler({"option": "_conn_opt", "value": value})
        assert fields["_serial_port"][1] == ("elrs_settings" if value == "1" else None)
        assert api.values["_serial_port"] == DEVICE_PATH
    assert api.ui.broadcast_ui.call_count == 4
    api.ui.broadcast_ui.assert_called_with("settings", replace_panels=False)
    handler({"option": "_serial_port", "value": DEVICE_PATH})
    assert api.ui.broadcast_ui.call_count == 4


def test_startup_refreshes_visibility_after_database_options_load(plugin, api):
    fields = {}
    api.fields.register_option.side_effect = lambda field, panel: fields.update(
        {field.name: (field, panel)})
    plugin.initialize(api)
    assert fields["_serial_port"][1] is None
    api.values.update(_conn_opt="1", _serial_port=DEVICE_PATH)
    handler = next(call.args[1] for call in api.events.on.call_args_list
                   if call.kwargs.get("name") == "elrs_serial_port_visibility_startup")
    handler({"_eventName": "startup"})
    assert fields["_serial_port"][1] == "elrs_settings"
    assert api.values["_serial_port"] == DEVICE_PATH


@pytest.mark.parametrize("path, expected", [(None, None), ("", None), ("  ", None),
                                           ("  " + DEVICE_PATH + "  ", DEVICE_PATH)])
def test_usb_passes_normalized_path_to_connection(plugin, api, path, expected):
    api.values.update(_conn_opt="1", _serial_port=path)
    controller = plugin.ELRSBackpack("elrs", "ELRS", api)
    controller._establish_connection = Mock()
    controller.start_connection()
    controller._establish_connection.assert_called_once_with(
        plugin.ConnectionTypeEnum.USB.type_, port=expected)


@pytest.mark.parametrize("selection", ["2", "3"])
def test_non_usb_connections_ignore_saved_usb_path(plugin, api, monkeypatch, selection):
    api.values.update(_conn_opt=selection, _serial_port=DEVICE_PATH, _socket_ip="netpack")
    backpack = sys.modules[plugin.__name__ + ".elrs_backpack"]
    monkeypatch.setattr(backpack.gevent, "sleep", Mock())
    monkeypatch.setattr(backpack.socket, "gethostbyname", lambda host: "192.0.2.1")
    controller = plugin.ELRSBackpack("elrs", "ELRS", api)
    controller._establish_connection = Mock()
    controller.start_connection()
    expected = {} if selection == "2" else {"ip_addr": "192.0.2.1"}
    assert controller._establish_connection.call_args.kwargs == expected
