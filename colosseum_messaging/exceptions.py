"""Messaging plugin errors."""

from __future__ import annotations


class MessagingError(RuntimeError):
    """Base error for colosseum-messaging."""


class MessagingCapabilityError(MessagingError):
    """Raised when a messaging API is unavailable for the current configuration."""
