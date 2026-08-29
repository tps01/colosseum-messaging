"""U-MSG-MQTT: MQTT sim publish/receive contract."""

from __future__ import annotations

from colosseum_messaging.mqtt.client import MqttClientWrapper


def test_sim_publish_receive_roundtrip() -> None:
    client = MqttClientWrapper(
        {"host": "127.0.0.1", "port": 1883, "topic": "device/#", "driver": "sim"},
    )
    client.publish("device/cmd", "on")
    msg = client.receive(timeout=0.5, topic="device/#")
    assert msg == {"topic": "device/cmd", "payload": "on"}
