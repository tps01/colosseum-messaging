"""Installed distribution metadata and plugin entry-point specifications."""

from importlib.metadata import distribution

import colosseum_messaging
import paho.mqtt.client  # noqa: F401 - importability smoke for declared deps
import paramiko  # noqa: F401
import redis  # noqa: F401
import scp  # noqa: F401
import zmq  # noqa: F401


def test_complete_runtime_dependencies_are_installed_by_default() -> None:
    metadata = distribution("colosseum-messaging")
    requirements = [requirement.lower() for requirement in metadata.requires or []]

    assert any(requirement.startswith("colosseum-core") for requirement in requirements)
    assert any(requirement.startswith("redis") for requirement in requirements)
    assert any(requirement.startswith("pyzmq") for requirement in requirements)
    assert any(requirement.startswith("paho-mqtt") for requirement in requirements)
    assert any(requirement.startswith("paramiko") for requirement in requirements)
    assert any(requirement.startswith("scp") for requirement in requirements)
    assert not metadata.metadata.get_all("Provides-Extra")


def test_plugin_entry_points_and_version_match_metadata() -> None:
    metadata = distribution("colosseum-messaging")
    entry_points = {
        (entry_point.group, entry_point.name): entry_point.value
        for entry_point in metadata.entry_points
    }

    assert entry_points[("colosseum.plugins", "messaging")] == "colosseum_messaging:register"
    assert colosseum_messaging.__version__ == metadata.version
