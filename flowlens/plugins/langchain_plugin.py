"""
FlowLens LangChain Plugin — Plugin-format wrapper around the LangChain auto-instrumentation.

This module exposes the LangChain monkey-patching as a proper :class:`BasePlugin`
subclass so it can be discovered and managed via the :class:`PluginRegistry`.

Backward compatibility:
    The original ``flowlens.sdk.auto_instrument._patch_langchain`` function and
    the top-level ``auto_instrument(["langchain"])`` API continue to work unchanged.
    This plugin simply delegates to those same helpers so there is no duplication.
"""

from __future__ import annotations

import logging

from flowlens.plugins import BasePlugin
from flowlens.sdk import auto_instrument as _ai_module

logger = logging.getLogger(__name__)


class LangChainPlugin(BasePlugin):
    """FlowLens plugin that instruments the LangChain Python SDK.

    Patches (each attempted independently; missing classes are silently skipped):
    - ``langchain_core.language_models.base.BaseLanguageModel.invoke``
    - ``langchain_core.language_models.base.BaseLanguageModel.ainvoke``
    - ``langchain.chains.base.Chain.__call__``
    - ``langchain.agents.agent.AgentExecutor._call``

    Calling :meth:`patch` is idempotent — applying it multiple times is safe
    because the underlying ``_patch_langchain`` helper tracks the ``_patched``
    registry.
    """

    name = "langchain"
    version = "0.1.0"

    def patch(self) -> None:
        """Apply LangChain instrumentation.

        Delegates to :func:`flowlens.sdk.auto_instrument._patch_langchain`.
        Idempotent: a second call is a no-op.
        """
        if "langchain" in _ai_module._patched:
            logger.debug("[LangChainPlugin] already patched — skipping")
            return
        _ai_module._patch_langchain()
        logger.info("[LangChainPlugin] patch() applied")

    def unpatch(self) -> None:
        """Remove LangChain instrumentation.

        Removes the entry from the ``_patched`` registry so that a subsequent
        call to ``patch()`` (or ``auto_instrument(["langchain"])``) will
        re-apply the patches.  If neither ``langchain`` nor ``langchain_core``
        is installed this is a silent no-op.
        """
        langchain_present = False
        try:
            import langchain_core  # type: ignore  # noqa: F401
            langchain_present = True
        except ImportError:
            pass

        if not langchain_present:
            try:
                import langchain  # type: ignore  # noqa: F401
                langchain_present = True
            except ImportError:
                pass

        if not langchain_present:
            logger.debug("[LangChainPlugin] langchain / langchain_core not installed — nothing to unpatch")
            return

        _ai_module._patched.discard("langchain")
        logger.info("[LangChainPlugin] unpatch() called — registry entry removed")
