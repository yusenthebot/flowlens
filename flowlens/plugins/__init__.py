"""
FlowLens Plugin Infrastructure — Abstract base class, registry, and discovery.

Plugin authors implement BasePlugin and register their plugin via the
``flowlens.plugins`` entry-point group in their package's pyproject.toml::

    [project.entry-points."flowlens.plugins"]
    my_plugin = "my_package.plugin:MyPlugin"

Built-in plugins (anthropic, openai, langchain) are located in this package
and can also be loaded by name through :func:`load_plugin`.
"""

from __future__ import annotations

import abc
import importlib
import logging
from typing import ClassVar

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BasePlugin
# ---------------------------------------------------------------------------

class BasePlugin(abc.ABC):
    """Abstract base class for all FlowLens instrumentation plugins.

    Subclasses must provide:
    - ``name``:    unique identifier string (e.g. ``"anthropic"``)
    - ``version``: plugin version string (e.g. ``"0.1.0"``)
    - ``patch()``:   apply monkey-patching / instrumentation
    - ``unpatch()``: remove monkey-patching / instrumentation
    """

    #: Unique plugin name — must be overridden in each subclass.
    name: ClassVar[str]

    #: Plugin version string — must be overridden in each subclass.
    version: ClassVar[str]

    @abc.abstractmethod
    def patch(self) -> None:
        """Apply instrumentation (monkey-patches, hooks, etc.)."""

    @abc.abstractmethod
    def unpatch(self) -> None:
        """Remove instrumentation previously applied by :meth:`patch`."""

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{type(self).__name__} name={self.name!r} version={self.version!r}>"


# ---------------------------------------------------------------------------
# PluginRegistry
# ---------------------------------------------------------------------------

class PluginRegistry:
    """Singleton registry for FlowLens plugins.

    Usage::

        registry = PluginRegistry.instance()
        registry.register(AnthropicPlugin())
        plugin = registry.get("anthropic")
        plugin.patch()
    """

    _singleton: PluginRegistry | None = None

    def __init__(self) -> None:
        self._plugins: dict[str, BasePlugin] = {}

    # ------------------------------------------------------------------
    # Singleton access
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls) -> PluginRegistry:
        """Return (or create) the process-wide singleton registry."""
        if cls._singleton is None:
            cls._singleton = cls()
        return cls._singleton

    @classmethod
    def _reset(cls) -> None:
        """Reset the singleton — intended for testing only."""
        cls._singleton = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, plugin: BasePlugin) -> None:
        """Register a plugin instance.

        If a plugin with the same name was already registered it will be
        replaced.

        Args:
            plugin: An instance of a :class:`BasePlugin` subclass.
        """
        if not isinstance(plugin, BasePlugin):
            raise TypeError(f"Expected a BasePlugin instance, got {type(plugin)!r}")
        self._plugins[plugin.name] = plugin
        logger.debug(f"[FlowLens] Plugin registered: {plugin.name!r} v{plugin.version}")

    def get(self, name: str) -> BasePlugin | None:
        """Return the plugin registered under *name*, or ``None``."""
        return self._plugins.get(name)

    def all(self) -> list[BasePlugin]:
        """Return all registered plugins."""
        return list(self._plugins.values())

    def names(self) -> list[str]:
        """Return all registered plugin names."""
        return list(self._plugins.keys())

    # ------------------------------------------------------------------
    # Discovery via entry-points
    # ------------------------------------------------------------------

    def discover(self) -> None:
        """Discover and register plugins via ``flowlens.plugins`` entry-points.

        Third-party packages expose plugins by declaring an entry-point in
        their ``pyproject.toml``::

            [project.entry-points."flowlens.plugins"]
            my_plugin = "my_package.plugin:MyPlugin"

        Each entry-point value must be a :class:`BasePlugin` *class* (not an
        instance); this method will instantiate it and register it.
        """
        try:
            from importlib.metadata import entry_points
        except ImportError:
            logger.warning("[FlowLens] importlib.metadata not available; skipping plugin discovery")
            return

        eps = entry_points(group="flowlens.plugins")
        for ep in eps:
            try:
                plugin_cls = ep.load()
                if not (isinstance(plugin_cls, type) and issubclass(plugin_cls, BasePlugin)):
                    logger.warning(
                        f"[FlowLens] Entry-point {ep.name!r} did not resolve to a BasePlugin "
                        f"subclass — skipping"
                    )
                    continue
                self.register(plugin_cls())
                logger.info(f"[FlowLens] Discovered plugin via entry-point: {ep.name!r}")
            except Exception as exc:
                logger.warning(f"[FlowLens] Failed to load plugin {ep.name!r}: {exc}")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

# Mapping from well-known names to the built-in plugin module / class.
_BUILTIN_PLUGINS: dict[str, str] = {
    "anthropic": "flowlens.plugins.anthropic_plugin:AnthropicPlugin",
    "openai": "flowlens.plugins.openai_plugin:OpenAIPlugin",
    "langchain": "flowlens.plugins.langchain_plugin:LangChainPlugin",
}


def discover_plugins() -> None:
    """Discover and register all plugins from the ``flowlens.plugins`` entry-point group.

    Delegates to :meth:`PluginRegistry.discover` on the singleton registry.
    """
    PluginRegistry.instance().discover()


def load_plugin(name: str) -> BasePlugin | None:
    """Load a plugin by name and register it with the singleton registry.

    Resolves built-in plugin names (``"anthropic"``, ``"openai"``,
    ``"langchain"``) automatically.  For custom plugins pass a fully-qualified
    ``"module.path:ClassName"`` string.

    Returns the loaded plugin instance, or ``None`` if loading fails.
    """
    registry = PluginRegistry.instance()

    # Return already-registered plugin if present
    existing = registry.get(name)
    if existing is not None:
        return existing

    # Resolve built-in shorthand names
    qualified = _BUILTIN_PLUGINS.get(name, name)

    if ":" not in qualified:
        logger.warning(
            f"[FlowLens] Cannot load plugin {name!r}: expected 'module:ClassName' format"
        )
        return None

    module_path, class_name = qualified.rsplit(":", 1)
    try:
        module = importlib.import_module(module_path)
        plugin_cls = getattr(module, class_name)
        if not (isinstance(plugin_cls, type) and issubclass(plugin_cls, BasePlugin)):
            logger.warning(
                f"[FlowLens] {qualified!r} is not a BasePlugin subclass — skipping"
            )
            return None
        plugin = plugin_cls()
        registry.register(plugin)
        return plugin
    except (ImportError, AttributeError) as exc:
        logger.warning(f"[FlowLens] Failed to load plugin {name!r} from {module_path!r}: {exc}")
        return None


__all__ = [
    "BasePlugin",
    "PluginRegistry",
    "discover_plugins",
    "load_plugin",
]
