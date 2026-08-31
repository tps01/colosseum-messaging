"""Colosseum messaging plugin (HTTP, Redis, ZMQ, MQTT, SSH)."""

from importlib import metadata

from colosseum.config.sections import ConfigSectionSpec
from colosseum.logging import get_logger
from colosseum.plugins.registry import PluginRegistry

from colosseum_messaging.connections import close_all

__colosseum_domain__ = "messaging"

try:
    __version__ = metadata.version("colosseum-messaging")
except metadata.PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

_logger = get_logger("colosseum.messaging")


def register(registry: PluginRegistry) -> None:
    from colosseum_messaging import api

    registry.register_namespace("messaging", api)
    _logger.debug("Registered col.messaging namespace")
    registry.register_shutdown(close_all)
    registry.register_config_section(
        ConfigSectionSpec(
            "messaging.http",
            "http_id",
            required_keys=("base_url",),
            optional_keys=("timeout", "verify_tls", "driver"),
        ),
    )
    registry.register_config_section(
        ConfigSectionSpec(
            "messaging.redis",
            "redis_id",
            required_keys=("host",),
            optional_keys=("port", "db", "username", "password", "timeout", "driver"),
        ),
    )
    registry.register_config_section(
        ConfigSectionSpec(
            "messaging.zmq",
            "zmq_id",
            required_keys=("endpoint", "socket"),
            optional_keys=("topic", "mode", "driver"),
        ),
    )
    registry.register_config_section(
        ConfigSectionSpec(
            "messaging.mqtt",
            "mqtt_id",
            required_keys=("host",),
            optional_keys=(
                "port",
                "client_id",
                "username",
                "password",
                "topic",
                "keepalive",
                "driver",
            ),
        ),
    )
    registry.register_config_section(
        ConfigSectionSpec(
            "messaging.ssh",
            "ssh_id",
            required_keys=("host", "username"),
            optional_keys=(
                "port",
                "password",
                "key_filename",
                "timeout",
                "driver",
                "auth",
                "platform",
            ),
        ),
    )
