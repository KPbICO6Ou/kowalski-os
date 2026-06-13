"""Security policy: risk level + path allowlist -> ALLOW / CONFIRM / DENY.
Confirmation is delegated to a ConfirmationProvider (CLI y/n, pending queue, tests)."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field as dc_field
from enum import StrEnum
from pathlib import Path
from typing import Any

from .tools.base import RiskLevel, ToolDef

# Paths that are never touched even with confirmation.
FORBIDDEN_ROOTS = ("/etc", "/usr", "/bin", "/sbin", "/boot", "/var", "/System", "/Library")


class Decision(StrEnum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass
class ConfirmRequest:
    tool: str
    args: dict[str, Any]
    risk: RiskLevel
    reason: str
    dangerous: bool = False
    danger_reason: str | None = None
    id: str = dc_field(default_factory=lambda: uuid.uuid4().hex)


class ConfirmationProvider(ABC):
    @abstractmethod
    async def confirm(self, request: ConfirmRequest) -> bool: ...


class AutoConfirm(ConfirmationProvider):
    """The `kow ask --yes` path: auto-approves routine actions (read/write/
    network) but NEVER an irreversible DESTRUCTIVE action or a command flagged
    as dangerous — those still need a real human."""

    async def confirm(self, request: ConfirmRequest) -> bool:
        if request.risk == RiskLevel.DESTRUCTIVE or request.dangerous:
            return False
        return True


class AutoDeny(ConfirmationProvider):
    async def confirm(self, request: ConfirmRequest) -> bool:
        return False


class InteractiveCliConfirmation(ConfirmationProvider):
    """y/n prompt on the terminal — the `kow ask` dev path."""

    async def confirm(self, request: ConfirmRequest) -> bool:
        import asyncio

        prompt = f"\n⚠ {request.tool} [{request.risk}] {request.reason}\n  args: {request.args}\n  allow? [y/N] "
        answer = await asyncio.get_running_loop().run_in_executor(None, input, prompt)
        return answer.strip().lower() in ("y", "yes")


class SecurityPolicy:
    def __init__(self, allowed_paths: list[Path], auto_allow_network: bool = False):
        self.allowed_paths = [p.resolve() for p in allowed_paths]
        self.auto_allow_network = auto_allow_network

    def evaluate(self, tool: ToolDef, args: dict[str, Any]) -> tuple[Decision, str]:
        """Returns (decision, reason)."""
        paths = self._extract_paths(tool, args)
        for path in paths:
            if self._is_forbidden(path):
                return Decision.DENY, f"path outside permitted area: {path}"

        if tool.risk == RiskLevel.READ:
            return Decision.ALLOW, "read-only tool"
        if tool.risk == RiskLevel.DESTRUCTIVE:
            return Decision.CONFIRM, "destructive action always requires confirmation"
        if tool.risk == RiskLevel.NETWORK:
            if self.auto_allow_network:
                return Decision.ALLOW, "network auto-allowed by config"
            return Decision.CONFIRM, "network action"
        # WRITE: allowed if all paths are inside the allowlist
        if all(self._is_allowed(p) for p in paths):
            return Decision.ALLOW, "write inside allowed paths"
        return Decision.CONFIRM, "write outside allowed paths"

    def _extract_paths(self, tool: ToolDef, args: dict[str, Any]) -> list[Path]:
        paths = []
        for name in tool.path_fields:
            value = args.get(name)
            if value:
                paths.append(Path(str(value)).expanduser().resolve())
        return paths

    def _is_allowed(self, path: Path) -> bool:
        return any(path.is_relative_to(root) for root in self.allowed_paths)

    def _is_forbidden(self, path: Path) -> bool:
        if self._is_allowed(path):
            return False
        # resolve() the roots too: on macOS /etc is a symlink to /private/etc
        return any(path.is_relative_to(Path(root).resolve()) for root in FORBIDDEN_ROOTS)
