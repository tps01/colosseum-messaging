"""U-MSG-MQTT: MQTT sim publish/receive specification."""

from __future__ import annotations

import pytest

from colosseum_messaging.mqtt.client import MqttClientWrapper, _topic_matches


def test_sim_publish_receive_roundtrip() -> None:
    client = MqttClientWrapper(
        {"host": "127.0.0.1", "port": 1883, "topic": "device/#", "driver": "sim"},
    )
    client.publish("device/cmd", "on")
    msg = client.receive(timeout=0.5, topic="device/#")
    assert msg == {"topic": "device/cmd", "payload": "on"}


@pytest.mark.parametrize(
    ("filter_topic", "message_topic", "expected"),
    [
        ("#", "$SYS/status", False),
        ("+/status", "$SYS/status", False),
        ("$SYS/#", "$SYS/status", True),
        ("#", "device/cmd", True),
        ("+/status", "device/status", True),
    ],
)
def test_topic_matches_respects_reserved_dollar_topics(
    filter_topic: str,
    message_topic: str,
    expected: bool,
) -> None:
    assert _topic_matches(filter_topic, message_topic) is expected


def test_sim_receive_skips_reserved_dollar_topics_for_hash() -> None:
    client = MqttClientWrapper(
        {"host": "127.0.0.1", "port": 1883, "topic": "#", "driver": "sim"},
    )
    client.publish("$SYS/status", "up")
    client.publish("device/cmd", "on")
    msg = client.receive(timeout=0.5, topic="#")
    assert msg == {"topic": "device/cmd", "payload": "on"}


def test_sim_receive_times_out_when_only_reserved_dollar_topic() -> None:
    client = MqttClientWrapper(
        {"host": "127.0.0.1", "port": 1883, "topic": "#", "driver": "sim"},
    )
    client.publish("$SYS/status", "up")
    with pytest.raises(TimeoutError, match="No MQTT message"):
        client.receive(timeout=0.2, topic="#")


def test_sim_receive_allows_explicit_dollar_subscription() -> None:
    client = MqttClientWrapper(
        {"host": "127.0.0.1", "port": 1883, "topic": "$SYS/#", "driver": "sim"},
    )
    client.publish("$SYS/status", "up")
    msg = client.receive(timeout=0.5, topic="$SYS/#")
    assert msg == {"topic": "$SYS/status", "payload": "up"}
