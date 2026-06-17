"""Pure-parser tests for the bluetooth.*/audio.* tools (no subprocess/hardware)."""

from kowalski.tools.base import RiskLevel
from kowalski.tools.bluetooth import (
    _default_sink,
    _is_audio,
    _parse_devices,
    _parse_sinks,
    _pick_sink,
    build_bluetooth_tools,
)


def test_parse_devices_keeps_only_mac_lines():
    text = (
        "Device 04:7F:0E:3C:4C:80 JBL Flip 5\n"
        "Device AA:BB:CC:DD:EE:FF My Phone\n"
        "noise line\n"
    )
    assert _parse_devices(text) == [
        ("04:7F:0E:3C:4C:80", "JBL Flip 5"),
        ("AA:BB:CC:DD:EE:FF", "My Phone"),
    ]


def test_is_audio_detects_speakers():
    assert _is_audio("Icon: audio-card\nClass: 0x240414")
    assert _is_audio("UUID: Audio Sink (0000110b-0000-1000-8000-00805f9b34fb)")
    assert _is_audio("Icon: headset")
    assert not _is_audio("Icon: phone\nClass: 0x5a020c")


def test_parse_sinks_and_default_and_pick():
    sinks_txt = (
        "48\talsa_output.pci-0000_00_1b.0.iec958-stereo\tPipeWire\ts32le\tSUSPENDED\n"
        "70\tbluez_output.04_7F_0E_3C_4C_80.1\tPipeWire\ts16le\tRUNNING\n"
    )
    sinks = _parse_sinks(sinks_txt)
    assert sinks == [
        ("48", "alsa_output.pci-0000_00_1b.0.iec958-stereo"),
        ("70", "bluez_output.04_7F_0E_3C_4C_80.1"),
    ]
    assert _default_sink("Default Sink: bluez_output.04_7F_0E_3C_4C_80.1\n") == \
        "bluez_output.04_7F_0E_3C_4C_80.1"
    assert _pick_sink(sinks, "bluez") == "bluez_output.04_7F_0E_3C_4C_80.1"
    assert _pick_sink(sinks, "IEC958") == "alsa_output.pci-0000_00_1b.0.iec958-stereo"
    assert _pick_sink(sinks, "nope") is None


def test_tool_set_names_and_risk():
    tools = {t.name: t for t in build_bluetooth_tools()}
    assert set(tools) == {
        "bluetooth.status", "bluetooth.scan", "bluetooth.connect_speaker",
        "audio.outputs", "audio.set_output",
    }
    assert tools["bluetooth.status"].risk is RiskLevel.READ
    assert tools["audio.outputs"].risk is RiskLevel.READ
    # WRITE (no path args) -> ALLOW, so these run over voice without a confirm.
    assert tools["bluetooth.connect_speaker"].risk is RiskLevel.WRITE
    assert tools["audio.set_output"].risk is RiskLevel.WRITE
