"""Sandboxed command execution.

Shell execution is the single highest-consequence capability of the agent
(risk #1), so it never runs a raw command directly. Every command goes through
a SandboxRunner:

  * BubblewrapRunner (Linux): isolates the command in a bubblewrap/firejail
    sandbox — read-only host root, a writable bind only for the working
    directory, no network, dies with the parent.
  * PlainRunner (macOS dev / CI): NO isolation. It exists only because bwrap is
    Linux-only; it logs a loud warning on every run so an unsandboxed execution
    is never silent.

Both runners enforce a timeout (killing the whole process group on expiry) and
cap captured output so a runaway command cannot exhaust memory.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import sys
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

logger = logging.getLogger("kowalski.sandbox")

# Per-stream capture cap. A command that floods stdout/stderr would otherwise
# pull its entire output into memory; we keep the first MAX_OUTPUT_BYTES and
# mark the truncation.
MAX_OUTPUT_BYTES = 64 * 1024
TRUNCATION_MARKER = "\n... [output truncated]"

# Only these environment variables are exposed to a command by default. The
# agent's process environment may hold secrets (Ollama/API tokens, IMAP/SMTP
# passwords); inheriting it wholesale would leak them into every command and
# defeat the sandbox, which otherwise isolates only the filesystem and network.
_SAFE_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TZ", "USER")


def _minimal_env(override: dict[str, str] | None) -> dict[str, str]:
    if override is not None:
        return override
    env = {k: os.environ[k] for k in _SAFE_ENV_KEYS if k in os.environ}
    env.setdefault("PATH", "/usr/bin:/bin")
    return env


@dataclass
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    sandboxed: bool


def _decode_and_cap(raw: bytes) -> str:
    """Decode bytes leniently and cap to MAX_OUTPUT_BYTES, appending a marker."""
    if len(raw) > MAX_OUTPUT_BYTES:
        text = raw[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        return text + TRUNCATION_MARKER
    return raw.decode("utf-8", errors="replace")


async def _communicate_with_timeout(
    proc: asyncio.subprocess.Process, timeout: float
) -> tuple[bytes, bytes, bool]:
    """Wait for the process, killing its process group on timeout.

    Returns (stdout, stderr, timed_out). The child is started in its own
    process group (start_new_session=True) so we can SIGKILL the whole group
    and not leak grandchildren on expiry.
    """
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout, stderr, False
    except (TimeoutError, asyncio.TimeoutError):
        _kill_process_group(proc)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        except (TimeoutError, asyncio.TimeoutError):
            stdout, stderr = b"", b""
        return stdout, stderr, True


def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


@runtime_checkable
class SandboxRunner(Protocol):
    async def run(
        self,
        command: str,
        cwd: str | None = None,
        timeout: float = 30.0,
        env: dict[str, str] | None = None,
    ) -> RunResult: ...


class PlainRunner:
    """Unsandboxed fallback (macOS dev / CI where bwrap/firejail are absent).

    Runs the command via the shell with no isolation. Emits a loud warning on
    every invocation so an unsandboxed execution is never silent.
    """

    sandboxed = False

    async def run(
        self,
        command: str,
        cwd: str | None = None,
        timeout: float = 30.0,
        env: dict[str, str] | None = None,
    ) -> RunResult:
        logger.warning(
            "UNSANDBOXED shell execution (no bwrap/firejail available): %r", command
        )
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            env=_minimal_env(env),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        stdout, stderr, timed_out = await _communicate_with_timeout(proc, timeout)
        return RunResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=_decode_and_cap(stdout),
            stderr=_decode_and_cap(stderr),
            timed_out=timed_out,
            sandboxed=False,
        )


# Read-only host paths bound into the sandbox so common tools still resolve.
_RO_BINDS = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc")


class BubblewrapRunner:
    """Linux sandbox via bubblewrap (`bwrap`), falling back to `firejail`.

    Guarantees on Linux:
      * host root filesystem is read-only (selected paths bound --ro-bind),
      * the ONLY writable location is the working directory,
      * no network access (--unshare-net),
      * the sandbox dies with the parent (--die-with-parent),
      * a private /tmp and /dev.

    Linux-only: on a host without bwrap/firejail, default_runner() picks
    PlainRunner instead.
    """

    sandboxed = True

    def __init__(self) -> None:
        self._bwrap = shutil.which("bwrap")
        self._firejail = shutil.which("firejail") if not self._bwrap else None
        if not self._bwrap and not self._firejail:
            raise RuntimeError("neither bwrap nor firejail is available")

    @staticmethod
    def available() -> bool:
        return bool(shutil.which("bwrap") or shutil.which("firejail"))

    def _bwrap_argv(self, command: str, cwd: str | None) -> list[str]:
        argv = [
            self._bwrap,
            "--die-with-parent",
            "--unshare-net",
            "--unshare-pid",
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
        ]
        for path in _RO_BINDS:
            if os.path.exists(path):
                argv += ["--ro-bind", path, path]
        if cwd:
            argv += ["--bind", cwd, cwd, "--chdir", cwd]
        argv += ["/bin/sh", "-c", command]
        return argv

    def _firejail_argv(self, command: str, cwd: str | None) -> list[str]:
        argv = [
            self._firejail,
            "--quiet",
            "--net=none",
            "--private-tmp",
        ]
        if cwd:
            # Restrict the writable home to the working directory.
            argv += [f"--private={cwd}"]
        argv += ["/bin/sh", "-c", command]
        return argv

    async def run(
        self,
        command: str,
        cwd: str | None = None,
        timeout: float = 30.0,
        env: dict[str, str] | None = None,
    ) -> RunResult:
        if self._bwrap:
            argv = self._bwrap_argv(command, cwd)
        else:
            argv = self._firejail_argv(command, cwd)
        # Minimal env so the sandbox does not leak the agent's secrets; bwrap
        # passes its own environment through to the child, so setting it here is
        # sufficient (no parent env reaches the sandboxed command).
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=_minimal_env(env),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        stdout, stderr, timed_out = await _communicate_with_timeout(proc, timeout)
        return RunResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=_decode_and_cap(stdout),
            stderr=_decode_and_cap(stderr),
            timed_out=timed_out,
            sandboxed=True,
        )


def default_runner() -> SandboxRunner:
    """BubblewrapRunner when a Linux sandbox is available, else PlainRunner."""
    if sys.platform.startswith("linux") and BubblewrapRunner.available():
        return BubblewrapRunner()
    return PlainRunner()
