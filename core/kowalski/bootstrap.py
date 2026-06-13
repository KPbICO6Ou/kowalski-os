"""Default tool set assembly."""

from __future__ import annotations

from .config import Config
from .journal import ActionJournal
from .policy import ConfirmationProvider, SecurityPolicy
from .scheduler import ReminderScheduler
from .store import Store
from .tools import apps, files, mail, notes, reminders, system
from .tools.registry import ToolRegistry


def build_default_registry(
    config: Config,
    store: Store,
    scheduler: ReminderScheduler,
    confirmer: ConfirmationProvider,
) -> ToolRegistry:
    policy = SecurityPolicy(
        allowed_paths=config.allowed_paths,
        auto_allow_network=config.get_bool("KOW_AUTO_ALLOW_NETWORK"),
    )
    registry = ToolRegistry(
        policy=policy,
        journal=ActionJournal(store),
        confirmer=confirmer,
        tool_timeout=float(config.get_int("KOW_TOOL_TIMEOUT")),
    )
    registry.register_all(system.TOOLS)
    registry.register_all(apps.TOOLS)
    registry.register_all(files.build_tools(config.allowed_paths))
    registry.register_all(notes.build_tools(store))
    registry.register_all(reminders.build_tools(scheduler))
    _register_mail_tools(registry, config, store)

    try:
        import kowindex.api  # noqa: F401
    except ImportError:
        pass  # indexer package not installed — files.search_semantic simply absent
    else:
        registry.register_all(files.build_semantic_tools(config))

    if config.get_bool("KOW_TOOLBOX_FS") and config.allowed_paths:
        try:
            from .tools.toolbox import build_filesystem_tools

            registry.register_all(
                build_filesystem_tools(
                    root=config.allowed_paths[0],
                    read_only=not config.get_bool("KOW_TOOLBOX_FS_WRITE"),
                )
            )
        except ImportError:
            pass  # pydantic-ai-toolbox not installed — fs.* tools simply absent

    if config.get_bool("KOW_TOOLBOX_SYSTEM"):
        try:
            from .tools.toolbox import build_system_tools

            registry.register_all(build_system_tools())
        except ImportError:
            pass  # pydantic-ai-toolbox not installed — system.* host-info tools absent
    return registry


def _register_mail_tools(registry: ToolRegistry, config: Config, store: Store) -> None:
    """Build the mail backend per KOW_MAIL_BACKEND and register mail.* tools.

    mock (default) → empty in-memory inbox so the capability exists in dev.
    imap → real IMAP/SMTP; if its optional deps aren't importable we skip the
    mail tools entirely rather than crash the daemon.
    """
    from .mail.drafts import DraftStore

    backend_kind = config.get("KOW_MAIL_BACKEND", "mock").lower()
    if backend_kind == "imap":
        from .mail.imap_smtp import ImapSmtpBackend

        if not ImapSmtpBackend.importable():
            return  # 'mail' extra not installed — mail tools simply absent
        backend = ImapSmtpBackend(config)
    else:
        from .mail.mock import MockMailBackend

        backend = MockMailBackend()
    registry.register_all(mail.build_tools(backend, DraftStore(store)))


def build_llm(config: Config, model_override: str = ""):
    """LLM transport per KOW_LLM: native ollama client or the pydantic-ai layer."""
    host = config.get("OLLAMA_HOST")
    model = model_override or config.get("OLLAMA_MODEL")
    temperature = float(config.get("KOW_TEMPERATURE"))
    if config.get("KOW_LLM") == "pydantic-ai":
        from .agent.pydantic_llm import PydanticAILLM

        return PydanticAILLM(
            host=host, model=model,
            pai_model=config.get("KOW_PAI_MODEL"), temperature=temperature,
        )
    from .agent.llm import OllamaLLM

    return OllamaLLM(host=host, model=model, temperature=temperature)
