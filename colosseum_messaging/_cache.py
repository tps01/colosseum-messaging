"""Runtime resource cache helpers for messaging connections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, TypeVar

if TYPE_CHECKING:
    import logging

T = TypeVar("T")


def cached_resource(
    cache: dict[str, object],
    key: str,
    loader: Callable[[], T],
    *,
    on_reuse: Callable[[], None] | None = None,
    on_open: Callable[[], None] | None = None,
) -> T:
    if key in cache:
        if on_reuse is not None:
            on_reuse()
        return cache[key]  # type: ignore[return-value]
    if on_open is not None:
        on_open()
    value = loader()
    cache[key] = value
    return value


def close_cached_resources(
    cache: dict[str, object],
    prefix_groups: tuple[tuple[str, ...], ...],
    *,
    logger: logging.Logger | None = None,
) -> None:
    keys_to_close: list[str] = []
    seen: set[str] = set()
    for group in prefix_groups:
        for key in list(cache):
            if key in seen:
                continue
            if any(key.startswith(prefix) for prefix in group):
                keys_to_close.append(key)
                seen.add(key)
    if keys_to_close and logger is not None:
        logger.debug("Closing %d cached resource(s)", len(keys_to_close))
    for key in keys_to_close:
        resource = cache.pop(key, None)
        close = getattr(resource, "close", None)
        if not callable(close):
            continue
        try:
            close()
        except Exception:
            if logger is not None:
                logger.exception("Failed to close cached resource %s", key)
