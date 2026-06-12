from pathlib import Path

import pytest

from kowalski.config import Config
from kowalski.journal import ActionJournal
from kowalski.policy import AutoConfirm, AutoDeny, SecurityPolicy
from kowalski.store import Store
from kowalski.tools.registry import ToolRegistry


@pytest.fixture
def tmp_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "test.db")
    yield store
    store.close()


@pytest.fixture
def journal(tmp_store: Store) -> ActionJournal:
    return ActionJournal(tmp_store)


@pytest.fixture
def policy(tmp_path: Path) -> SecurityPolicy:
    return SecurityPolicy(allowed_paths=[tmp_path])


@pytest.fixture
def registry(policy: SecurityPolicy, journal: ActionJournal) -> ToolRegistry:
    return ToolRegistry(policy=policy, journal=journal, confirmer=AutoConfirm(), tool_timeout=5.0)


@pytest.fixture
def deny_registry(policy: SecurityPolicy, journal: ActionJournal) -> ToolRegistry:
    return ToolRegistry(policy=policy, journal=journal, confirmer=AutoDeny(), tool_timeout=5.0)


@pytest.fixture
def config(tmp_path: Path) -> Config:
    values = dict(
        KOW_DB_PATH=str(tmp_path / "kow.db"),
        KOW_ALLOWED_PATHS=str(tmp_path),
        KOW_MAX_ITERATIONS="8",
        KOW_TOOL_TIMEOUT="5",
        KOW_AUTO_ALLOW_NETWORK="0",
        OLLAMA_HOST="http://127.0.0.1:11434",
        OLLAMA_MODEL="test",
    )
    return Config(values)
