"""
FlowLens OpenAI Plugin — Plugin-format wrapper around the OpenAI auto-instrumentation.

This module exposes the OpenAI monkey-patching as a proper :class:`BasePlugin`
subclass so it can be discovered and managed via the :class:`PluginRegistry`.

Backward compatibility:
    The original ``flowlens.sdk.auto_instrument._patch_openai`` function and
    the top-level ``auto_instrument(["openai"])`` API continue to work unchanged.
    This plugin simply delegates to those same helpers so there is no duplication.
"""

from __future__ import annotations

import logging

from flowlens.plugins import BasePlugin
from flowlens.sdk import auto_instrument as _ai_module

logger = logging.getLogger(__name__)


class OpenAIPlugin(BasePlugin):
    """FlowLens plugin that instruments the OpenAI Python SDK.

    Patches (new client API — openai >= 1.0):
    - ``openai.OpenAI.chat.completions.create`` (sync, including stream=True)
    - ``openai.AsyncOpenAI.chat.completions.create`` (async, including stream=True)

    Patches (legacy API — openai < 1.0):
    - ``openai.ChatCompletion.create``
    - ``openai.ChatCompletion.acreate``

    Calling :meth:`patch` is idempotent — applying it multiple times is safe
    because the underlying ``_patch_openai`` helper tracks the ``_patched``
    registry.
    """

    name = "openai"
    version = "0.1.0"

    def patch(self) -> None:
        """Apply OpenAI instrumentation.

        Delegates to :func:`flowlens.sdk.auto_instrument._patch_openai`.
        Idempotent: a second call is a no-op.
        """
        if "openai" in _ai_module._patched:
            logger.debug("[OpenAIPlugin] already patched — skipping")
            return
        _ai_module._patch_openai()
        logger.info("[OpenAIPlugin] patch() applied")

    def unpatch(self) -> None:
        """Remove OpenAI instrumentation.

        Removes the entry from the ``_patched`` registry so that a subsequent
        call to ``patch()`` (or ``auto_instrument(["openai"])``) will
        re-apply the patches.  If the library is not installed this is a
        silent no-op.
        """
        try:
            import openai  # type: ignore  # noqa: F401
        except ImportError:
            logger.debug("[OpenAIPlugin] openai not installed — nothing to unpatch")
            return

        _ai_module._patched.discard("openai")
        logger.info("[OpenAIPlugin] unpatch() called — registry entry removed")
