from __future__ import annotations

import logging

from colosseum.config.loader import ConfigError
from colosseum.context import require_context
from colosseum.resource_cache import cached_resource, close_cached_resources

from colosseum_messaging.http.client import HttpClientWrapper
from colosseum_messaging.mqtt.client import MqttClientWrapper
from colosseum_messaging.redis.client import RedisClientWrapper
from colosseum_messaging.zmq.client import ZmqClientWrapper

_logger = logging.getLogger("colosseum.messaging")


def _require_config_item(section: str, item_id: int) -> dict[str, object]:
    ctx = require_context()
    if ctx.config is None:
        raise ConfigError("Configuration is not loaded. Call col.config.load_config(path).")
    return dict(ctx.config.require_item(section, item_id))


def get_http_client(http_id: int) -> HttpClientWrapper:
    ctx = require_context()
    key = f"messaging:http:{http_id}"
    cfg = _require_config_item("messaging.http", http_id)
    driver = str(cfg.get("driver", "http")).lower()

    def _open() -> HttpClientWrapper:
        return HttpClientWrapper(cfg)

    return cached_resource(
        ctx.resource_cache,
        key,
        _open,
        on_reuse=lambda: _logger.debug("Reusing cached HTTP client messaging.http id=%s", http_id),
        on_open=lambda: _logger.debug(
            "Opening HTTP client messaging.http id=%s driver=%s base_url=%s",
            http_id,
            driver,
            cfg.get("base_url"),
        ),
    )


def get_redis_client(redis_id: int) -> RedisClientWrapper:
    ctx = require_context()
    key = f"messaging:redis:{redis_id}"
    cfg = _require_config_item("messaging.redis", redis_id)
    driver = str(cfg.get("driver", "redis")).lower()

    def _open() -> RedisClientWrapper:
        return RedisClientWrapper(cfg)

    return cached_resource(
        ctx.resource_cache,
        key,
        _open,
        on_reuse=lambda: _logger.debug(
            "Reusing cached Redis client messaging.redis id=%s", redis_id
        ),
        on_open=lambda: _logger.debug(
            "Opening Redis client messaging.redis id=%s driver=%s host=%s",
            redis_id,
            driver,
            cfg.get("host"),
        ),
    )


def get_zmq_client(zmq_id: int) -> ZmqClientWrapper:
    ctx = require_context()
    key = f"messaging:zmq:{zmq_id}"
    cfg = _require_config_item("messaging.zmq", zmq_id)
    driver = str(cfg.get("driver", "zmq")).lower()

    def _open() -> ZmqClientWrapper:
        return ZmqClientWrapper(cfg)

    return cached_resource(
        ctx.resource_cache,
        key,
        _open,
        on_reuse=lambda: _logger.debug("Reusing cached ZMQ client messaging.zmq id=%s", zmq_id),
        on_open=lambda: _logger.debug(
            "Opening ZMQ client messaging.zmq id=%s driver=%s endpoint=%s socket=%s",
            zmq_id,
            driver,
            cfg.get("endpoint"),
            cfg.get("socket"),
        ),
    )


def get_mqtt_client(mqtt_id: int) -> MqttClientWrapper:
    ctx = require_context()
    key = f"messaging:mqtt:{mqtt_id}"
    cfg = _require_config_item("messaging.mqtt", mqtt_id)
    driver = str(cfg.get("driver", "mqtt")).lower()

    def _open() -> MqttClientWrapper:
        return MqttClientWrapper(cfg)

    return cached_resource(
        ctx.resource_cache,
        key,
        _open,
        on_reuse=lambda: _logger.debug("Reusing cached MQTT client messaging.mqtt id=%s", mqtt_id),
        on_open=lambda: _logger.debug(
            "Opening MQTT client messaging.mqtt id=%s driver=%s host=%s",
            mqtt_id,
            driver,
            cfg.get("host"),
        ),
    )


def close_all() -> None:
    ctx = require_context()
    close_cached_resources(
        ctx.resource_cache,
        (
            (
                "messaging:http:",
                "messaging:redis:",
                "messaging:zmq:",
                "messaging:mqtt:",
            ),
        ),
        logger=_logger,
    )
