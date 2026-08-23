"""Process-local mailboxes for messaging sim drivers."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class _MailboxStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queues: dict[str, deque[tuple[str, str]]] = defaultdict(deque)

    def publish(self, mailbox_key: str, topic: str, payload: str) -> None:
        with self._lock:
            self._queues[mailbox_key].append((topic, payload))

    def receive(self, mailbox_key: str, timeout: float) -> tuple[str, str] | None:
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            with self._lock:
                queue = self._queues.get(mailbox_key)
                if queue:
                    return queue.popleft()
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.01)


SIM_MAILBOX = _MailboxStore()

# Shared in-memory Redis KV for sim driver (process-local).
_SIM_REDIS_LOCK = threading.Lock()
_SIM_REDIS_KV: dict[str, str] = {}


def sim_redis_set(name: str, value: str) -> None:
    with _SIM_REDIS_LOCK:
        _SIM_REDIS_KV[name] = value


def sim_redis_get(name: str) -> str | None:
    with _SIM_REDIS_LOCK:
        return _SIM_REDIS_KV.get(name)


def sim_redis_clear() -> None:
    with _SIM_REDIS_LOCK:
        _SIM_REDIS_KV.clear()
