"""Process-local mailboxes for messaging sim drivers."""

from __future__ import annotations

import itertools
import threading
import time
from collections import defaultdict, deque


class _MailboxStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens = itertools.count(1)
        # mailbox_key -> token -> per-subscriber queue
        self._subscribers: dict[str, dict[int, deque[tuple[str, str]]]] = defaultdict(dict)
        self._token_keys: dict[int, str] = {}
        # Publishes that arrived before any subscriber; copied into each new
        # subscriber queue so lazy ZMQ SUB construction still sees earlier PUBs.
        self._pending: dict[str, deque[tuple[str, str]]] = defaultdict(deque)

    def subscribe(self, mailbox_key: str) -> int:
        """Create a per-subscriber queue for ``mailbox_key``; return its token."""
        with self._lock:
            token = next(self._tokens)
            queue: deque[tuple[str, str]] = deque(self._pending.get(mailbox_key, ()))
            self._subscribers[mailbox_key][token] = queue
            self._token_keys[token] = mailbox_key
            return token

    def unsubscribe(self, token: int) -> None:
        """Remove the subscriber queue identified by ``token``."""
        with self._lock:
            mailbox_key = self._token_keys.pop(token, None)
            if mailbox_key is None:
                return
            queues = self._subscribers.get(mailbox_key)
            if queues is not None:
                queues.pop(token, None)
                if not queues:
                    self._subscribers.pop(mailbox_key, None)
                    self._pending.pop(mailbox_key, None)

    def publish(self, mailbox_key: str, topic: str, payload: str) -> None:
        with self._lock:
            queues = self._subscribers.get(mailbox_key)
            if queues:
                for queue in queues.values():
                    queue.append((topic, payload))
                self._pending.pop(mailbox_key, None)
            else:
                self._pending[mailbox_key].append((topic, payload))

    def receive(self, token: int, timeout: float) -> tuple[str, str] | None:
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            with self._lock:
                mailbox_key = self._token_keys.get(token)
                if mailbox_key is not None:
                    queue = self._subscribers.get(mailbox_key, {}).get(token)
                    if queue:
                        return queue.popleft()
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.01)


SIM_MAILBOX = _MailboxStore()

# Shared in-memory Redis KV for sim driver, keyed by mailbox prefix + name.
_SIM_REDIS_LOCK = threading.Lock()
_SIM_REDIS_KV: dict[str, str] = {}


def sim_redis_set(prefix: str, name: str, value: str) -> None:
    with _SIM_REDIS_LOCK:
        _SIM_REDIS_KV[f"{prefix}:{name}"] = value


def sim_redis_get(prefix: str, name: str) -> str | None:
    with _SIM_REDIS_LOCK:
        return _SIM_REDIS_KV.get(f"{prefix}:{name}")


def sim_redis_clear() -> None:
    with _SIM_REDIS_LOCK:
        _SIM_REDIS_KV.clear()
