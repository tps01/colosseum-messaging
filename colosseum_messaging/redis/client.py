from __future__ import annotations

from typing import TYPE_CHECKING

from colosseum.logging import get_logger

import redis
from colosseum_messaging.sim import SIM_MAILBOX, sim_redis_get, sim_redis_set

if TYPE_CHECKING:
    from collections.abc import Mapping

_logger = get_logger("colosseum.messaging.redis")


class RedisClientWrapper:
    def __init__(self, config: Mapping[str, object]) -> None:
        self._sim = str(config.get("driver", "redis")).lower() == "sim"
        self._client: redis.Redis | None = None
        self._pubsub: object | None = None
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
            sim_redis_set(name, value)
            return
        if self._client is None:
            raise RuntimeError("Redis client is not connected")
        self._client.set(name, value)

    def get(self, name: str) -> str | None:
        _logger.debug("Redis GET %s", name)
        if self._sim:
            return sim_redis_get(name)
        if self._client is None:
            raise RuntimeError("Redis client is not connected")
        value = self._client.get(name)
        if value is None:
            return None
        return str(value)

    def publish(self, channel: str, message: str) -> None:
        _logger.debug("Redis PUBLISH %s", channel)
        if self._sim:
            SIM_MAILBOX.publish(f"{self._mailbox_prefix}:{channel}", channel, message)
            return
        if self._client is None:
            raise RuntimeError("Redis client is not connected")
        self._client.publish(channel, message)

    def receive(self, channel: str, timeout: float = 1.0) -> dict[str, str]:
        _logger.debug("Redis RECEIVE %s timeout=%ss", channel, timeout)
        if self._sim:
            item = SIM_MAILBOX.receive(f"{self._mailbox_prefix}:{channel}", timeout)
            if item is None:
                raise TimeoutError(f"No Redis message on channel {channel!r} within {timeout}s")
            topic, payload = item
            return {"topic": topic, "payload": payload}
        if self._client is None:
            raise RuntimeError("Redis client is not connected")
        if self._pubsub is None:
            self._pubsub = self._client.pubsub(  # type: ignore[no-untyped-call]
                ignore_subscribe_messages=True,
            )
            self._pubsub.subscribe(channel)  # type: ignore[union-attr]
        pubsub = self._pubsub
        message = pubsub.get_message(timeout=timeout)  # type: ignore[union-attr]
        if message is None or message.get("type") != "message":
            deadline = timeout
            waited = 0.0
            step = min(0.1, max(0.01, timeout))
            while waited < deadline:
                message = pubsub.get_message(timeout=step)  # type: ignore[union-attr]
                waited += step
                if message is not None and message.get("type") == "message":
                    break
            else:
                raise TimeoutError(f"No Redis message on channel {channel!r} within {timeout}s")
        data = message.get("data")
        payload = "" if data is None else str(data)
        return {"topic": channel, "payload": payload}

    def close(self) -> None:
        if self._pubsub is not None:
            try:
                close = getattr(self._pubsub, "close", None)
                if callable(close):
                    close()
            except Exception:
                _logger.exception("Failed to close Redis pubsub")
            self._pubsub = None
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                _logger.exception("Failed to close Redis client")
            self._client = None
