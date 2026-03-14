"""
FlowLens custom exception hierarchy.

All FlowLens-specific errors derive from FlowLensError so callers can
catch the entire family with a single ``except FlowLensError`` clause.
"""

from __future__ import annotations


class FlowLensError(Exception):
    """Base exception for all FlowLens errors."""


class StorageError(FlowLensError):
    """Raised when a storage operation fails (read, write, migration, etc.)."""


class ExportError(FlowLensError):
    """Raised when exporting trace data to an external system fails."""


class ValidationError(FlowLensError):
    """Raised when input data fails validation before being processed."""


class RateLimitError(FlowLensError):
    """Raised when a client exceeds the allowed request rate."""
