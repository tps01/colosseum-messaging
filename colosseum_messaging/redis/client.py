from __future__ import annotations

import time
from typing import TYPE_CHECKING

from colosseum.logging import get_logger

import redis
from colosseum_messaging._pump import PumpHandle, topic_payload
from colosseum_messaging.sim import SIM_MAILBOX, sim_redis_get, sim_redis_set

if TYPE_CHECKING:
    from collections.abc import Mapping

    from colosseum_messaging._pump import Hook

_logger = get_logger("colosseum.messaging.redis")
_ALLOWED_DRIVERS = frozenset({"sim", "redis"})


class RedisClientWrapper:
    def __init__(self, config: Mapping[str, object]) -> None:
        driver = str(config.get("driver", "redis")).lower()
        if driver not in _ALLOWED_DRIVERS:
            raise ValueError(
                f"messaging.redis driver must be one of {sorted(_ALLOWED_DRIVERS)}, got {driver!r}",
            )
        self._sim = driver == "sim"
        self._client: redis.Redis | None = None
        self._pubsub: object | None = None
        self._subscribed_channel: str | None = None
        self._listen_pump = PumpHandle()
        self._send_pump = PumpHandle()
        self._mailbox_prefix = f"redis:{config.get('host')}:{config.get('port', 6379)}"
        if self._sim:
            _logger.debug("Redis client sim mode enabled")
            return
        kwargs: dict[str, object] = {
            "host": str(config["host"]),
            "port": int(str(config.get("port", 6379))),
            "db": int(str(config.get("db", 0))),
            "socket_timeout": float(str(config.get("timeout", 10.0))),
            "decode_responses": True,
        }
        username = config.get("username")
        password = config.get("password")
        if username is not None:
            kwargs["username"] = str(username)
        if password is not None:
            kwargs["password"] = str(password)
        self._client = redis.Redis(**kwargs)  # type: ignore[arg-type]

    def set(self, name: str, value: str) -> None:
        _logger.debug("Redis SET %s", name)
        if self._sim:
            sim_redis_set(self._mailbox_prefix, name, value)
            return
        if self._client is None:
            raise RuntimeError("Redis client is not connected")
        self._client.set(name, value)

    def get(self, name: str) -> str | None:
        _logger.debug("Redis GET %s", name)
        if self._sim:
            return sim_redis_get(self._mailbox_prefix, name)
        if self._client is None:
            raise RuntimeError("Redis client is not connected")
        value = self._client.get(name)
        if value is None:
            return None
        return str(value)

    def publish(self, channel: str, message: str) -> None:
        sender = getattr(self, "_send_pump", None)
        if sender is not None and sender.running():
            raise RuntimeError("Redis send pump owns this client")
        self._publish(channel, message)

    def _publish(self, channel: str, message: str) -> None:
        _logger.debug("Redis PUBLISH %s", channel)
        if self._sim:
            SIM_MAILBOX.publish(f"{self._mailbox_prefix}:{channel}", channel, message)
            return
        if self._client is None:
            raise RuntimeError("Redis client is not connected")
        self._client.publish(channel, message)

    def receive(self, channel: str, timeout: float = 1.0) -> dict[str, str]:
        listen = getattr(self, "_listen_pump", None)
        if listen is not None and listen.running():
            raise RuntimeError("Redis listen pump owns this client")
        return self._receive(channel, timeout)

    def _receive(self, channel: str, timeout: float = 1.0) -> dict[str, str]:
        _logger.debug("Redis RECEIVE %s timeout=%ss", channel, timeout)
        if self._sim:
            item = SIM_MAILBOX.receive(f"{self._mailbox_prefix}:{channel}", timeout)
            if item is None:
                raise TimeoutError(f"No Redis message on channel {channel!r} within {timeout}s")
            topic, payload = item
            return {"topic": topic, "payload": payload}
        if self._client is None:
            raise RuntimeError("Redis client is not connected")
        if self._pubsub is None or self._subscribed_channel != channel:
            if self._pubsub is not None:
                try:
                    close = getattr(self._pubsub, "close", None)
                    if callable(close):
                        close()
                except Exception:
                    _logger.exception("Failed to close Redis pubsub before resubscribe")
                self._pubsub = None
            self._pubsub = self._client.pubsub(  # type: ignore[no-untyped-call]
                ignore_subscribe_messages=True,
            )
            self._pubsub.subscribe(channel)  # type: ignore[union-attr]
            self._subscribed_channel = channel
        pubsub = self._pubsub
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining < 0:
                remaining = 0.0
            if time.monotonic() > deadline:
                raise TimeoutError(f"No Redis message on channel {channel!r} within {timeout}s")
            message = pubsub.get_message(timeout=remaining)  # type: ignore[union-attr]
            if message is not None and message.get("type") == "message":
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(f"No Redis message on channel {channel!r} within {timeout}s")
        data = message.get("data")
        payload = "" if data is None else str(data)
        return {"topic": channel, "payload": payload}

    def start_listen(self, channel: str, on_message: Hook) -> None:
        def poll(timeout: float) -> dict[str, str] | None:
            return self._receive(channel, timeout)

        self._listen_pump.start(poll=poll, on_message=on_message, name="redis-listen")

    def stop_listen(self) -> None:
        self._listen_pump.stop()

    def start_sender(self) -> None:
        self._send_pump.start(offer=self._offer_send, name="redis-send")

    def enqueue(self, channel: str, message: str) -> None:
        self._send_pump.submit((channel, message))

    def stop_sender(self) -> None:
        self._send_pump.stop()

    def _offer_send(self, item: object) -> None:
        channel, message = topic_payload(item)
        self._publish(channel, message)

    def close(self) -> None:
        self.stop_listen()
        self.stop_sender()
        if self._pubsub is not None:
            try:
                close = getattr(self._pubsub, "close", None)
                if callable(close):
                    close()
            except Exception:
                _logger.exception("Failed to close Redis pubsub")
            self._pubsub = None
            self._subscribed_channel = None
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                _logger.exception("Failed to close Redis client")
            self._client = None
