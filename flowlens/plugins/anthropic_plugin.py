"""
FlowLens Anthropic Plugin — Plugin-format wrapper around the Anthropic auto-instrumentation.

This module exposes the Anthropic monkey-patching as a proper :class:`BasePlugin`
subclass so it can be discovered and managed via the :class:`PluginRegistry`.

Backward compatibility:
    The original ``flowlens.sdk.auto_instrument._patch_anthropic`` function and
    the top-level ``auto_instrument(["anthropic"])`` API continue to work unchanged.
    This plugin simply delegates to those same helpers so there is no duplication.
"""

from __future__ import annotations

import logging

from flowlens.plugins import BasePlugin
from flowlens.sdk import auto_instrument as _ai_module

logger = logging.getLogger(__name__)


class AnthropicPlugin(BasePlugin):
    """FlowLens plugin that instruments the Anthropic Python SDK.

    Patches:
    - ``anthropic.Anthropic.messages.create`` (sync)
    - ``anthropic.AsyncAnthropic.messages.create`` (async)

    Calling :meth:`patch` is idempotent — applying it multiple times is safe
    because the underlying ``_patch_anthropic`` helper tracks the ``_patched``
    registry.
    """

    name = "anthropic"
    version = "0.1.0"

    def patch(self) -> None:
        """Apply Anthropic instrumentation.

        Delegates to :func:`flowlens.sdk.auto_instrument._patch_anthropic`.
        Idempotent: a second call is a no-op.
        """
        if "anthropic" in _ai_module._patched:
            logger.debug("[AnthropicPlugin] already patched — skipping")
            return
        _ai_module._patch_anthropic()
        logger.info("[AnthropicPlugin] patch() applied")

    def unpatch(self) -> None:
        """Remove Anthropic instrumentation.

        Note: The underlying ``_patch_anthropic`` stores the original functions
        locally in closures, so true un-patching would require storing
        references to the originals at patch time.  This implementation
        removes the entry from the ``_patched`` registry so that a subsequent
        call to ``patch()`` (or ``auto_instrument(["anthropic"])``) will
        re-apply the patches.  If the library is not installed this is a
        silent no-op.
        """
        try:
            import anthropic  # type: ignore  # noqa: F401
        except ImportError:
            logger.debug("[AnthropicPlugin] anthropic not installed — nothing to unpatch")
            return

        _ai_module._patched.discard("anthropic")
        logger.info("[AnthropicPlugin] unpatch() called — registry entry removed")
