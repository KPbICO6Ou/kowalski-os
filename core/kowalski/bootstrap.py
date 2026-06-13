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

    from .convsearch import ConversationSearch  # noqa: F401  (kept local to bootstrap)
    from .tools.search import build_conversation_search_tools, build_search_tools

    registry.register_all(build_search_tools(config))
    registry.register_all(build_conversation_search_tools(store))

    if config.get_bool("KOW_MEMORY"):
        _register_memory(registry, config, store)

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

    if config.get_bool("KOW_VISION"):
        from .tools.vision import build_vision_tools

        registry.register_all(build_vision_tools(config))
    if config.get_bool("KOW_UIAUTO"):
        from .tools.uiauto import build_uiauto_tools

        registry.register_all(build_uiauto_tools(config))
    if config.get_bool("KOW_SHELL"):
        from .tools.shell import build_shell_tools

        registry.register_all(build_shell_tools(config))
    if config.get_bool("KOW_RECIPES"):
        _register_recipe_tools(registry, config, scheduler)

    if config.get_bool("KOW_CHECKLIST"):
        from .tools.checklist import build_checklist_tools

        registry.register_all(build_checklist_tools())

    _register_plugins(registry, config)

    from .tools.mcp import build_mcp_tools

    registry.register_all(build_mcp_tools(config))
    return registry


def _register_plugins(registry: ToolRegistry, config: Config) -> None:
    """Load user plugin tools from KOW_PLUGINS_DIR (default ~/.config/kowalski/plugins)."""
    from pathlib import Path

    from .plugins import DEFAULT_PLUGINS_DIR, load_plugin_tools

    plugins_dir = (
        Path(config.get("KOW_PLUGINS_DIR")).expanduser()
        if config.get("KOW_PLUGINS_DIR")
        else DEFAULT_PLUGINS_DIR
    )
    registry.register_all(load_plugin_tools(plugins_dir))


def _register_memory(registry: ToolRegistry, config: Config, store: Store) -> None:
    """Register memory.*/profile.* tools and attach a MemoryContextProvider to
    the registry so the agent loop can inject profile + recalled memories."""
    from .memory.context import MemoryContextProvider
    from .memory.embedder import OllamaEmbedder
    from .memory.store import MemoryStore
    from .tools.memory import build_memory_tools

    embedder = OllamaEmbedder(
        config.get("OLLAMA_HOST"), config.get("KOW_EMBED_MODEL", "nomic-embed-text")
    )
    memory_store = MemoryStore(store)
    registry.register_all(build_memory_tools(memory_store, embedder))
    registry.context_provider = MemoryContextProvider(
        memory_store, embedder, k=config.get_int("KOW_MEMORY_RECALL_K")
    )


def _register_recipe_tools(
    registry: ToolRegistry, config: Config, scheduler: ReminderScheduler
) -> None:
    """Wire the recipe engine (it needs the built registry to run steps and the
    scheduler to arm time/interval triggers) and stash it on the registry so the
    daemon can arm saved recipes once the scheduler is started."""
    from pathlib import Path

    from .recipes.engine import RecipeEngine
    from .recipes.store import DEFAULT_RECIPES_DIR, RecipeStore
    from .tools.recipes import build_recipe_tools

    recipe_dir = Path(config.get("KOW_RECIPES_DIR") or str(DEFAULT_RECIPES_DIR)).expanduser()
    engine = RecipeEngine(RecipeStore(recipe_dir), registry, scheduler.aps)
    registry.register_all(build_recipe_tools(engine))
    registry.recipe_engine = engine


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
