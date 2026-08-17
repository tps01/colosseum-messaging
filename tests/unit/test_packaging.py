"""Installed distribution metadata and plugin entry-point contracts."""

from importlib.metadata import distribution

import colosseum_messaging
import paho.mqtt.client
import paramiko

import redis
import zmq


def test_complete_runtime_dependencies_are_installed_by_default() -> None:
    metadata = distribution("colosseum-messaging")
    requirements = [requirement.lower() for requirement in metadata.requires or []]

    assert any(requirement.startswith("colosseum-core") for requirement in requirements)
    assert any(requirement.startswith("redis") for requirement in requirements)
    assert any(requirement.startswith("pyzmq") for requirement in requirements)
    assert any(requirement.startswith("paho-mqtt") for requirement in requirements)
    assert any(requirement.startswith("paramiko") for requirement in requirements)
    extras = set(metadata.metadata.get_all("Provides-Extra") or [])
    assert extras.issubset({"test", "static"})
    assert redis.Redis is not None
    assert zmq.Context is not None
    assert paho.mqtt.client.Client is not None
    assert paramiko.SSHClient is not None


def test_plugin_entry_points_and_version_match_metadata() -> None:
    metadata = distribution("colosseum-messaging")
    entry_points = {
        (entry_point.group, entry_point.name): entry_point.value
        for entry_point in metadata.entry_points
    }

    assert entry_points[("colosseum.plugins", "messaging")] == "colosseum_messaging:register"
    assert (
        entry_points[("colosseum.docgen", "messaging")]
        == "colosseum_messaging.docgen_entry:spec"
    )
    assert colosseum_messaging.__version__ == metadata.version
