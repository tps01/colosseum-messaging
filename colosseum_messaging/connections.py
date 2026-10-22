from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, TypeVar

from colosseum.config.loader import ConfigError
from colosseum.context import get_context
from colosseum.logging import get_logger

from colosseum_messaging._cache import cached_resource, close_cached_resources
from colosseum_messaging.http.client import HttpClientWrapper
from colosseum_messaging.mqtt.client import MqttClientWrapper
from colosseum_messaging.redis.client import RedisClientWrapper
from colosseum_messaging.ssh.client import SSHClientWrapper, _connection_attempts
from colosseum_messaging.zmq.client import ZmqClientWrapper

if TYPE_CHECKING:
    from collections.abc import Callable

_logger = get_logger("colosseum.messaging")

T = TypeVar("T")


def _require_config_item(section: str, item_id: int) -> dict[str, object]:
    ctx = get_context()
    if ctx.config is None:
        raise ConfigError("Configuration is not loaded. Call col.config.load_config(path).")
    return dict(ctx.config.require_item(section, item_id))


def _cached_client(
    *,
    section: str,
    item_id: int,
    cache_prefix: str,
    wrapper_cls: Callable[[dict[str, object]], T],
    default_driver: str,
    detail: Callable[[dict[str, object]], str],
) -> T:
    ctx = get_context()
    key = f"{cache_prefix}:{item_id}"
    cfg = _require_config_item(section, item_id)
    driver = str(cfg.get("driver", default_driver)).lower()

    def _open() -> T:
        return wrapper_cls(cfg)

    return cached_resource(
        ctx.resource_cache,
        key,
        _open,
        on_reuse=lambda: _logger.debug("Reusing cached %s id=%s", section, item_id),
        on_open=lambda: _logger.debug(
            "Opening %s id=%s driver=%s %s",
            section,
            item_id,
            driver,
            detail(cfg),
        ),
    )


def get_http_client(http_id: int) -> HttpClientWrapper:
    return _cached_client(
        section="messaging.http",
        item_id=http_id,
        cache_prefix="messaging:http",
        wrapper_cls=HttpClientWrapper,
        default_driver="http",
        detail=lambda cfg: f"base_url={cfg.get('base_url')}",
    )


def get_redis_client(redis_id: int) -> RedisClientWrapper:
    return _cached_client(
        section="messaging.redis",
        item_id=redis_id,
        cache_prefix="messaging:redis",
        wrapper_cls=RedisClientWrapper,
        default_driver="redis",
        detail=lambda cfg: f"host={cfg.get('host')}",
    )


def get_zmq_client(zmq_id: int) -> ZmqClientWrapper:
    return _cached_client(
        section="messaging.zmq",
        item_id=zmq_id,
        cache_prefix="messaging:zmq",
        wrapper_cls=ZmqClientWrapper,
        default_driver="zmq",
        detail=lambda cfg: (
            f"endpoint={cfg.get('endpoint')} socket={cfg.get('socket')}"
        ),
    )


def get_mqtt_client(mqtt_id: int) -> MqttClientWrapper:
    return _cached_client(
        section="messaging.mqtt",
        item_id=mqtt_id,
        cache_prefix="messaging:mqtt",
        wrapper_cls=MqttClientWrapper,
        default_driver="mqtt",
        detail=lambda cfg: f"host={cfg.get('host')}",
    )


def get_ssh_client(ssh_id: int, *, retries: int = 3) -> SSHClientWrapper:
    _connection_attempts(retries)
    return _cached_client(
        section="messaging.ssh",
        item_id=ssh_id,
        cache_prefix="messaging:ssh",
        wrapper_cls=partial(SSHClientWrapper, retries=retries),
        default_driver="ssh",
        detail=lambda cfg: f"host={cfg.get('host')}",
    )


def close_all() -> None:
    ctx = get_context()
    close_cached_resources(
        ctx.resource_cache,
        (
            (
                "messaging:http:",
                "messaging:redis:",
                "messaging:zmq:",
                "messaging:mqtt:",
                "messaging:ssh:",
            ),
        ),
        logger=_logger,
    )
