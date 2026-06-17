"""bluetooth.* + audio.* tools: connect a Bluetooth speaker and route sound to it.

Drives `bluetoothctl` (BlueZ) for scan/pair/connect and `pactl` (PipeWire /
PulseAudio) for output routing. Connecting/pairing and changing the default sink
are WRITE with no path args, so they resolve to ALLOW (no confirmation) — that is
what lets "подключи колонку" work over voice (where confirmations are auto-denied).
Each handler returns a ToolResult whose `content` is the line the LLM relays/speaks."""

from __future__ import annotations

import asyncio
import re
import shutil

from pydantic import BaseModel, Field

from .base import RiskLevel, ToolDef, ToolResult

SCAN_SECONDS = 8
_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


async def _run(*cmd: str, timeout: float = 12.0) -> tuple[int, str]:
    """Run a command, capturing combined output; never raises."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, out.decode("utf-8", "replace")
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not found"
    except (asyncio.TimeoutError, Exception):  # noqa: BLE001 - surface as a failed run
        return 124, "command timed out or failed"


# -- pure parsers (unit-tested) ----------------------------------------------

def _parse_devices(text: str) -> list[tuple[str, str]]:
    """`bluetoothctl devices` -> [(mac, name)] from 'Device <MAC> <name>' lines."""
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        parts = line.strip().split(" ", 2)
        if len(parts) >= 3 and parts[0] == "Device" and _MAC_RE.match(parts[1]):
            out.append((parts[1], parts[2]))
    return out


def _is_audio(info_text: str) -> bool:
    """True if a `bluetoothctl info` blob looks like a speaker/headset."""
    t = info_text.lower()
    return "audio-card" in t or "audio sink" in t or "headset" in t or "0x2404" in t


def _parse_sinks(text: str) -> list[tuple[str, str]]:
    """`pactl list short sinks` -> [(id, name)]."""
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        cols = line.split("\t")
        if len(cols) >= 2 and cols[0].strip().isdigit():
            out.append((cols[0].strip(), cols[1].strip()))
    return out


def _default_sink(info_text: str) -> str:
    for line in info_text.splitlines():
        if line.strip().lower().startswith("default sink:"):
            return line.split(":", 1)[1].strip()
    return ""


def _pick_sink(sinks: list[tuple[str, str]], query: str) -> str | None:
    q = query.lower()
    return next((name for _id, name in sinks if q in name.lower()), None)


# -- shared bluetooth/audio helpers ------------------------------------------

async def _scan_devices() -> list[tuple[str, str]]:
    await _run("bluetoothctl", "power", "on", timeout=8)
    await _run("bluetoothctl", "--timeout", str(SCAN_SECONDS), "scan", "on",
               timeout=SCAN_SECONDS + 6)
    _, devs = await _run("bluetoothctl", "devices")
    return _parse_devices(devs)


async def _audio_flagged(devices: list[tuple[str, str]]) -> list[tuple[str, str, bool]]:
    async def check(mac: str, name: str) -> tuple[str, str, bool]:
        _, info = await _run("bluetoothctl", "info", mac, timeout=6)
        return mac, name, _is_audio(info)

    return list(await asyncio.gather(*(check(m, n) for m, n in devices))) if devices else []


async def _move_streams(sink: str) -> None:
    _, ins = await _run("pactl", "list", "short", "sink-inputs", timeout=6)
    for line in ins.splitlines():
        sid = line.split("\t")[0].strip()
        if sid.isdigit():
            await _run("pactl", "move-sink-input", sid, sink, timeout=6)


async def _route_to_bt(mac: str) -> bool:
    """Make the BlueZ sink for `mac` the default output (it may take a moment to appear)."""
    token = mac.replace(":", "_").upper()
    for _ in range(6):
        _, sinks_txt = await _run("pactl", "list", "short", "sinks", timeout=6)
        sinks = _parse_sinks(sinks_txt)
        sink = (next((n for _i, n in sinks if "bluez" in n.lower() and token in n.upper()), None)
                or next((n for _i, n in sinks if "bluez" in n.lower()), None))
        if sink:
            await _run("pactl", "set-default-sink", sink, timeout=6)
            await _move_streams(sink)
            return True
        await asyncio.sleep(0.6)
    return False


# -- tool handlers -----------------------------------------------------------

class NoArgs(BaseModel):
    pass


class ConnectSpeakerArgs(BaseModel):
    name: str | None = Field(
        default=None,
        description="Speaker name (or MAC); omit to auto-pick the only audio device in range",
    )


class SetOutputArgs(BaseModel):
    name: str = Field(description="Output name or substring, e.g. 'bluez', 'HDMI', the speaker name")


async def bluetooth_status(args: NoArgs) -> ToolResult:
    _, show = await _run("bluetoothctl", "show")
    powered = "powered: yes" in show.lower()
    if not powered:
        return ToolResult(ok=True, content="Bluetooth adapter is powered off.",
                          data={"powered": False})
    _, conn = await _run("bluetoothctl", "devices", "Connected")
    devices = _parse_devices(conn)
    if devices:
        names = ", ".join(n for _m, n in devices)
        return ToolResult(ok=True, content=f"Bluetooth is on. Connected: {names}.",
                          data={"powered": True, "connected": devices})
    return ToolResult(ok=True, content="Bluetooth is on. Nothing connected.",
                      data={"powered": True, "connected": []})


async def bluetooth_scan(args: NoArgs) -> ToolResult:
    if not shutil.which("bluetoothctl"):
        return ToolResult(ok=False, content="bluetoothctl is not installed on this machine.")
    flagged = await _audio_flagged(await _scan_devices())
    audio = [(m, n) for m, n, a in flagged if a]
    data = {"devices": [{"mac": m, "name": n, "is_audio": a} for m, n, a in flagged]}
    if audio:
        names = "; ".join(n for _m, n in audio)
        return ToolResult(ok=True, content=f"Found {len(audio)} audio device(s): {names}.",
                          data=data)
    return ToolResult(
        ok=True,
        content="No speakers found. Put the speaker in pairing mode (hold its Bluetooth "
                "button until it blinks), then ask again.",
        data=data,
    )


async def bluetooth_connect_speaker(args: ConnectSpeakerArgs) -> ToolResult:
    if not shutil.which("bluetoothctl"):
        return ToolResult(ok=False, content="bluetoothctl is not installed on this machine.")
    query = (args.name or "").strip()

    if _MAC_RE.match(query):
        mac, name = query.upper(), query
    else:
        flagged = await _audio_flagged(await _scan_devices())
        audio = [(m, n) for m, n, a in flagged if a]
        if query:
            cand = ([(m, n) for m, n, _a in flagged if query.lower() in n.lower()])
            if not cand:
                return ToolResult(ok=True, content=f"No device matching '{query}' found — put "
                                  "the speaker in pairing mode and try again.")
            mac, name = cand[0]
        elif len(audio) == 1:
            mac, name = audio[0]
        elif len(audio) > 1:
            names = ", ".join(n for _m, n in audio)
            return ToolResult(ok=True, content=f"Found several speakers: {names}. Which one?",
                              data={"audio": [{"mac": m, "name": n} for m, n in audio]})
        else:
            return ToolResult(ok=True, content="No speaker found. Put it in pairing mode (hold "
                              "the Bluetooth button until it blinks) and ask again.")

    await _run("bluetoothctl", "power", "on", timeout=8)
    await _run("bluetoothctl", "pair", mac, timeout=12)
    await _run("bluetoothctl", "trust", mac, timeout=6)
    _, conn = await _run("bluetoothctl", "connect", mac, timeout=12)
    _, info = await _run("bluetoothctl", "info", mac, timeout=6)
    if "connected: yes" not in info.lower():
        return ToolResult(ok=False, content=f"Couldn't connect to {name}. Make sure it's on, in "
                          f"range and in pairing mode. ({conn.strip()[:100]})")
    routed = await _route_to_bt(mac)
    if not routed:
        # A single connect often doesn't bring up the A2DP transport, so the audio
        # server never creates the sink. A fresh re-connect reliably does.
        await _run("bluetoothctl", "disconnect", mac, timeout=6)
        await asyncio.sleep(1.5)
        await _run("bluetoothctl", "connect", mac, timeout=12)
        routed = await _route_to_bt(mac)
    tail = (" Sound now plays through it." if routed else
            " It's paired, but the system didn't create an audio output for it — its "
            "Bluetooth audio (A2DP) profile isn't active. Check `audio.outputs`.")
    return ToolResult(ok=True, content=f"Connected to {name}.{tail}",
                      data={"mac": mac, "name": name, "routed": routed})


async def audio_outputs(args: NoArgs) -> ToolResult:
    if not shutil.which("pactl"):
        return ToolResult(ok=False, content="pactl is not available on this machine.")
    _, sinks_txt = await _run("pactl", "list", "short", "sinks", timeout=6)
    _, info = await _run("pactl", "info", timeout=6)
    sinks = _parse_sinks(sinks_txt)
    default = _default_sink(info)
    lines = [f"{'*' if n == default else ' '} {n}" for _id, n in sinks]
    return ToolResult(ok=True, content="Audio outputs (* = current):\n" + "\n".join(lines),
                      data={"sinks": [n for _id, n in sinks], "default": default})


async def audio_set_output(args: SetOutputArgs) -> ToolResult:
    if not shutil.which("pactl"):
        return ToolResult(ok=False, content="pactl is not available on this machine.")
    _, sinks_txt = await _run("pactl", "list", "short", "sinks", timeout=6)
    sinks = _parse_sinks(sinks_txt)
    sink = _pick_sink(sinks, args.name)
    if not sink:
        avail = ", ".join(n for _id, n in sinks) or "(none)"
        return ToolResult(ok=False, content=f"No output matching '{args.name}'. Available: {avail}")
    await _run("pactl", "set-default-sink", sink, timeout=6)
    await _move_streams(sink)
    return ToolResult(ok=True, content=f"Audio output set to {sink}.", data={"default": sink})


def build_bluetooth_tools() -> list[ToolDef]:
    return [
        ToolDef(
            name="bluetooth.status",
            description="Bluetooth adapter state and which devices are connected.",
            args_model=NoArgs, risk=RiskLevel.READ, handler=bluetooth_status,
        ),
        ToolDef(
            name="bluetooth.scan",
            description="Power on Bluetooth and scan for nearby devices; flags speakers/headsets.",
            args_model=NoArgs, risk=RiskLevel.WRITE, handler=bluetooth_scan,
        ),
        ToolDef(
            name="bluetooth.connect_speaker",
            description="Connect a Bluetooth speaker / headphones and route system sound to it. "
                        "Use this for requests like 'подключи колонку', 'connect the speaker', "
                        "'наушники'. Omit `name` to auto-find the speaker in pairing mode.",
            args_model=ConnectSpeakerArgs, risk=RiskLevel.WRITE,
            handler=bluetooth_connect_speaker,
        ),
        ToolDef(
            name="audio.outputs",
            description="List audio output devices (sinks) and which one is the current default.",
            args_model=NoArgs, risk=RiskLevel.READ, handler=audio_outputs,
        ),
        ToolDef(
            name="audio.set_output",
            description="Set the default audio output (sink) by name/substring and move playback to it.",
            args_model=SetOutputArgs, risk=RiskLevel.WRITE, handler=audio_set_output,
        ),
    ]
