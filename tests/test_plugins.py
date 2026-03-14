"""
Tests for the FlowLens plugin infrastructure:
  - BasePlugin interface
  - PluginRegistry registration / discovery
  - Built-in provider plugins (AnthropicPlugin, OpenAIPlugin, LangChainPlugin)
"""

from __future__ import annotations

import logging
import sys
import types
from unittest.mock import patch

import pytest

from flowlens.plugins import BasePlugin, PluginRegistry, discover_plugins, load_plugin
from flowlens.sdk import auto_instrument as _ai_module

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_registry():
    """Isolate each test: give it a fresh PluginRegistry singleton."""
    PluginRegistry._reset()
    yield
    PluginRegistry._reset()


@pytest.fixture(autouse=True)
def reset_patched():
    """Restore _patched registry between tests."""
    original = _ai_module._patched.copy()
    _ai_module._patched.clear()
    yield
    _ai_module._patched.clear()
    _ai_module._patched.update(original)


# ---------------------------------------------------------------------------
# Concrete stub plugin used throughout the tests
# ---------------------------------------------------------------------------

class StubPlugin(BasePlugin):
    name = "stub"
    version = "1.2.3"

    def __init__(self):
        self.patched = False
        self.unpatched = False

    def patch(self) -> None:
        self.patched = True

    def unpatch(self) -> None:
        self.unpatched = True


# ---------------------------------------------------------------------------
# BasePlugin interface
# ---------------------------------------------------------------------------

class TestBasePlugin:
    def test_cannot_instantiate_abstract_base(self):
        """BasePlugin itself cannot be instantiated (missing abstract methods)."""
        with pytest.raises(TypeError):
            BasePlugin()  # type: ignore[abstract]

    def test_concrete_subclass_must_implement_patch_and_unpatch(self):
        """A subclass missing patch/unpatch raises TypeError on instantiation."""

        class Incomplete(BasePlugin):
            name = "incomplete"
            version = "0.0.0"
            # patch() and unpatch() deliberately omitted

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_stub_plugin_has_correct_metadata(self):
        plugin = StubPlugin()
        assert plugin.name == "stub"
        assert plugin.version == "1.2.3"

    def test_stub_plugin_patch_called(self):
        plugin = StubPlugin()
        plugin.patch()
        assert plugin.patched is True

    def test_stub_plugin_unpatch_called(self):
        plugin = StubPlugin()
        plugin.unpatch()
        assert plugin.unpatched is True

    def test_top_level_import(self):
        """BasePlugin and PluginRegistry are importable from the top-level package."""
        from flowlens import BasePlugin as BP
        from flowlens import PluginRegistry as PR
        assert BP is BasePlugin
        assert PR is PluginRegistry


# ---------------------------------------------------------------------------
# PluginRegistry
# ---------------------------------------------------------------------------

class TestPluginRegistry:
    def test_instance_returns_singleton(self):
        r1 = PluginRegistry.instance()
        r2 = PluginRegistry.instance()
        assert r1 is r2

    def test_register_and_get(self):
        registry = PluginRegistry.instance()
        plugin = StubPlugin()
        registry.register(plugin)
        assert registry.get("stub") is plugin

    def test_get_unknown_returns_none(self):
        registry = PluginRegistry.instance()
        assert registry.get("does_not_exist") is None

    def test_names_after_registration(self):
        registry = PluginRegistry.instance()
        registry.register(StubPlugin())
        assert "stub" in registry.names()

    def test_all_returns_list(self):
        registry = PluginRegistry.instance()
        registry.register(StubPlugin())
        plugins = registry.all()
        assert isinstance(plugins, list)
        assert len(plugins) == 1

    def test_register_replaces_existing_same_name(self):
        registry = PluginRegistry.instance()
        p1 = StubPlugin()
        p2 = StubPlugin()
        registry.register(p1)
        registry.register(p2)
        assert registry.get("stub") is p2

    def test_register_rejects_non_plugin(self):
        registry = PluginRegistry.instance()
        with pytest.raises(TypeError):
            registry.register("not a plugin")  # type: ignore[arg-type]

    def test_discover_plugins_function_delegates_to_registry(self):
        """discover_plugins() populates the singleton registry from entry-points."""
        # With no real entry-points registered, discover() should run without error.
        discover_plugins()  # Should not raise


# ---------------------------------------------------------------------------
# load_plugin — built-in names
# ---------------------------------------------------------------------------

class TestLoadPlugin:
    def test_load_anthropic_plugin(self):
        plugin = load_plugin("anthropic")
        assert plugin is not None
        assert plugin.name == "anthropic"

    def test_load_openai_plugin(self):
        plugin = load_plugin("openai")
        assert plugin is not None
        assert plugin.name == "openai"

    def test_load_langchain_plugin(self):
        plugin = load_plugin("langchain")
        assert plugin is not None
        assert plugin.name == "langchain"

    def test_load_plugin_registers_in_registry(self):
        load_plugin("anthropic")
        assert PluginRegistry.instance().get("anthropic") is not None

    def test_load_same_plugin_twice_returns_same_instance(self):
        p1 = load_plugin("anthropic")
        p2 = load_plugin("anthropic")
        assert p1 is p2

    def test_load_unknown_name_returns_none(self, caplog):
        with caplog.at_level(logging.WARNING, logger="flowlens.plugins"):
            result = load_plugin("totally_unknown_plugin")
        assert result is None

    def test_load_bad_qualified_name_returns_none(self, caplog):
        """A qualified name without ':' is logged and returns None."""
        with caplog.at_level(logging.WARNING, logger="flowlens.plugins"):
            result = load_plugin("no_colon_here")
        assert result is None

    def test_load_nonexistent_module_returns_none(self, caplog):
        """A well-formed but nonexistent module path returns None."""
        with caplog.at_level(logging.WARNING, logger="flowlens.plugins"):
            result = load_plugin("nonexistent.module:SomeClass")
        assert result is None


# ---------------------------------------------------------------------------
# AnthropicPlugin
# ---------------------------------------------------------------------------

class TestAnthropicPlugin:
    def test_plugin_loads(self):
        from flowlens.plugins.anthropic_plugin import AnthropicPlugin
        p = AnthropicPlugin()
        assert p.name == "anthropic"
        assert p.version == "0.1.0"

    def test_patch_calls_underlying_patcher_when_not_yet_patched(self):
        from flowlens.plugins.anthropic_plugin import AnthropicPlugin

        called = []
        original_patcher = _ai_module._patch_anthropic

        def fake_patch():
            called.append(True)
            _ai_module._patched.add("anthropic")

        _ai_module._patch_anthropic = fake_patch
        try:
            AnthropicPlugin().patch()
        finally:
            _ai_module._patch_anthropic = original_patcher

        assert called, "Expected _patch_anthropic to be called"

    def test_patch_is_idempotent(self):
        """Calling patch() when already patched is a no-op."""
        from flowlens.plugins.anthropic_plugin import AnthropicPlugin
        _ai_module._patched.add("anthropic")

        called = []
        original_patcher = _ai_module._patch_anthropic

        def fake_patch():
            called.append(True)

        _ai_module._patch_anthropic = fake_patch
        try:
            AnthropicPlugin().patch()
        finally:
            _ai_module._patch_anthropic = original_patcher

        assert not called, "_patch_anthropic should NOT be called when already patched"

    def test_unpatch_removes_from_registry(self):
        from flowlens.plugins.anthropic_plugin import AnthropicPlugin
        _ai_module._patched.add("anthropic")

        # Stub out the anthropic import so unpatch doesn't fail
        fake_anthropic = types.ModuleType("anthropic")
        with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
            AnthropicPlugin().unpatch()

        assert "anthropic" not in _ai_module._patched

    def test_unpatch_without_library_is_silent(self):
        """If anthropic is not installed, unpatch() does not raise."""
        from flowlens.plugins.anthropic_plugin import AnthropicPlugin
        with patch.dict(sys.modules, {"anthropic": None}):
            AnthropicPlugin().unpatch()  # should not raise


# ---------------------------------------------------------------------------
# OpenAIPlugin
# ---------------------------------------------------------------------------

class TestOpenAIPlugin:
    def test_plugin_loads(self):
        from flowlens.plugins.openai_plugin import OpenAIPlugin
        p = OpenAIPlugin()
        assert p.name == "openai"
        assert p.version == "0.1.0"

    def test_patch_calls_underlying_patcher_when_not_yet_patched(self):
        from flowlens.plugins.openai_plugin import OpenAIPlugin

        called = []
        original_patcher = _ai_module._patch_openai

        def fake_patch():
            called.append(True)
            _ai_module._patched.add("openai")

        _ai_module._patch_openai = fake_patch
        try:
            OpenAIPlugin().patch()
        finally:
            _ai_module._patch_openai = original_patcher

        assert called, "Expected _patch_openai to be called"

    def test_patch_is_idempotent(self):
        """Calling patch() when already patched is a no-op."""
        from flowlens.plugins.openai_plugin import OpenAIPlugin
        _ai_module._patched.add("openai")

        called = []
        original_patcher = _ai_module._patch_openai

        def fake_patch():
            called.append(True)

        _ai_module._patch_openai = fake_patch
        try:
            OpenAIPlugin().patch()
        finally:
            _ai_module._patch_openai = original_patcher

        assert not called, "_patch_openai should NOT be called when already patched"

    def test_unpatch_removes_from_registry(self):
        from flowlens.plugins.openai_plugin import OpenAIPlugin
        _ai_module._patched.add("openai")

        fake_openai = types.ModuleType("openai")
        with patch.dict(sys.modules, {"openai": fake_openai}):
            OpenAIPlugin().unpatch()

        assert "openai" not in _ai_module._patched

    def test_unpatch_without_library_is_silent(self):
        """If openai is not installed, unpatch() does not raise."""
        from flowlens.plugins.openai_plugin import OpenAIPlugin
        with patch.dict(sys.modules, {"openai": None}):
            OpenAIPlugin().unpatch()  # should not raise


# ---------------------------------------------------------------------------
# LangChainPlugin
# ---------------------------------------------------------------------------

class TestLangChainPlugin:
    def test_plugin_loads(self):
        from flowlens.plugins.langchain_plugin import LangChainPlugin
        p = LangChainPlugin()
        assert p.name == "langchain"
        assert p.version == "0.1.0"

    def test_patch_calls_underlying_patcher_when_not_yet_patched(self):
        from flowlens.plugins.langchain_plugin import LangChainPlugin

        called = []
        original_patcher = _ai_module._patch_langchain

        def fake_patch():
            called.append(True)
            _ai_module._patched.add("langchain")

        _ai_module._patch_langchain = fake_patch
        try:
            LangChainPlugin().patch()
        finally:
            _ai_module._patch_langchain = original_patcher

        assert called, "Expected _patch_langchain to be called"

    def test_patch_is_idempotent(self):
        """Calling patch() when already patched is a no-op."""
        from flowlens.plugins.langchain_plugin import LangChainPlugin
        _ai_module._patched.add("langchain")

        called = []
        original_patcher = _ai_module._patch_langchain

        def fake_patch():
            called.append(True)

        _ai_module._patch_langchain = fake_patch
        try:
            LangChainPlugin().patch()
        finally:
            _ai_module._patch_langchain = original_patcher

        assert not called, "_patch_langchain should NOT be called when already patched"

    def test_unpatch_removes_from_registry(self):
        from flowlens.plugins.langchain_plugin import LangChainPlugin
        _ai_module._patched.add("langchain")

        fake_langchain_core = types.ModuleType("langchain_core")
        with patch.dict(sys.modules, {"langchain_core": fake_langchain_core}):
            LangChainPlugin().unpatch()

        assert "langchain" not in _ai_module._patched

    def test_unpatch_without_library_is_silent(self):
        """If neither langchain nor langchain_core is installed, unpatch() does not raise."""
        from flowlens.plugins.langchain_plugin import LangChainPlugin
        with patch.dict(sys.modules, {"langchain": None, "langchain_core": None}):
            LangChainPlugin().unpatch()  # should not raise


# ---------------------------------------------------------------------------
# Top-level package exports
# ---------------------------------------------------------------------------

class TestTopLevelExports:
    def test_base_plugin_exported(self):
        import flowlens
        assert hasattr(flowlens, "BasePlugin")
        assert flowlens.BasePlugin is BasePlugin

    def test_plugin_registry_exported(self):
        import flowlens
        assert hasattr(flowlens, "PluginRegistry")
        assert flowlens.PluginRegistry is PluginRegistry

    def test_discover_plugins_exported(self):
        import flowlens
        assert hasattr(flowlens, "discover_plugins")
        assert callable(flowlens.discover_plugins)

    def test_load_plugin_exported(self):
        import flowlens
        assert hasattr(flowlens, "load_plugin")
        assert callable(flowlens.load_plugin)
