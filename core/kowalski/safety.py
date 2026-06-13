"""Dangerous-command denylist.

`classify_command` is a coarse, high-signal heuristic over a raw shell command
string. It NEVER hard-blocks: it only flags a command as dangerous so the tool
registry can force a human confirmation (the gate), even under `--yes`. A None
return means "no obvious danger detected" — it is best-effort, not a guarantee.
"""

from __future__ import annotations

import re

# Each entry: (compiled pattern, human-readable reason). Patterns are matched
# case-insensitively against the whole command string.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # rm with recursive AND force. Handles combined flags (-rf, -fr, -Rf) and
    # separate flags in any order (-r -f, --recursive --force, -f -r).
    (
        re.compile(
            r"\brm\b.*"
            r"(?:"
            # one combined short flag holding both r and f, e.g. -rf / -fr
            r"-[a-z]*r[a-z]*f[a-z]*\b|-[a-z]*f[a-z]*r[a-z]*\b"
            # OR a recursive flag anywhere AND a force flag anywhere
            r"|(?=.*(?:-[a-z]*r[a-z]*\b|--recursive))(?=.*(?:-[a-z]*f[a-z]*\b|--force))"
            r")",
            re.IGNORECASE,
        ),
        "recursive forced delete (rm -rf) can destroy data irreversibly",
    ),
    # Filesystem creation / disk partitioning
    (
        re.compile(r"\bmkfs(\.\w+)?\b", re.IGNORECASE),
        "mkfs formats a filesystem and destroys existing data",
    ),
    (
        re.compile(r"\bfdisk\b", re.IGNORECASE),
        "fdisk repartitions a disk and can destroy data",
    ),
    # dd writing to a device
    (
        re.compile(r"\bdd\b.*\bof=\s*/dev/", re.IGNORECASE),
        "dd writing to a device can overwrite a disk",
    ),
    # Raw redirect into a block device (> /dev/sda, > /dev/nvme0n1, ...)
    (
        re.compile(r">\s*/dev/(sd[a-z]|nvme\d|disk\d|hd[a-z]|vd[a-z])", re.IGNORECASE),
        "redirecting output into a raw disk device can corrupt it",
    ),
    # Fork bomb :(){ :|: };:  (tolerant of whitespace)
    (
        re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&?\s*\}", re.IGNORECASE),
        "fork bomb will exhaust system resources",
    ),
    # Remote code execution: curl/wget ... piped into a shell/interpreter
    (
        re.compile(
            r"\b(curl|wget)\b.*\|\s*(sudo\s+)?(sh|bash|zsh|python\d?|perl|ruby)\b",
            re.IGNORECASE,
        ),
        "piping a downloaded script straight into a shell runs untrusted remote code",
    ),
    # chmod -R 777 (world-writable, recursive)
    (
        re.compile(r"\bchmod\b.*(-[a-z]*r[a-z]*\b|--recursive).*\b777\b", re.IGNORECASE),
        "chmod -R 777 makes files world-writable and is a security risk",
    ),
    # Power state changes
    (
        re.compile(r"\b(shutdown|reboot|halt|poweroff)\b", re.IGNORECASE),
        "power command will shut down or restart the machine",
    ),
]


def classify_command(command: str) -> str | None:
    """Return a human-readable danger reason for `command`, or None if it looks
    benign. Coarse and case-insensitive; intended to FLAG (force confirmation),
    never to hard-block."""
    if not command:
        return None
    for pattern, reason in _PATTERNS:
        if pattern.search(command):
            return reason
    return None
