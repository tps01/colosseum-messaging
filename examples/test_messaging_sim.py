"""
Example: messaging plugin sim smoke (HTTP, Redis, ZMQ, MQTT, SSH).

Run:
  python examples/test_messaging_sim.py
  colosseum run examples/test_messaging_sim.py --config examples/configs/config.messaging.sim.toml
"""

from __future__ import annotations

import os
from pathlib import Path

import colosseum as col

_CONFIG = (
    Path(__file__).resolve().parent
    / "configs"
    / os.environ.get("COLOSSEUM_BENCH_CONFIG", "config.messaging.sim.toml")
)


def main() -> None:
    col.config.load_config(str(_CONFIG))

    col.messaging.http.get(http_id=1, path="/health", key="health")
    col.messaging.http.verify_status(key="health", expected=200)
    col.messaging.http.verify_body_match(key="health", pattern=r"GET /health")

    col.messaging.redis.set(redis_id=1, name="foo", value="bar")
    col.messaging.redis.get(redis_id=1, name="foo", key="foo")
    col.messaging.redis.verify_value_match(key="foo", pattern=r"^bar$")
    col.messaging.redis.publish(redis_id=1, channel="events", message="ping")
    col.messaging.redis.receive(redis_id=1, channel="events", key="redis_evt")

    col.messaging.zmq.send(zmq_id=1, payload="hello", topic="t1")
    col.messaging.zmq.receive(zmq_id=2, key="zmq_msg")
    col.messaging.zmq.verify_payload_match(key="zmq_msg", pattern=r"hello")

    col.messaging.mqtt.publish(mqtt_id=1, topic="device/cmd", payload="on")
    col.messaging.mqtt.receive(mqtt_id=1, key="mqtt_msg", topic="device/#")
    col.messaging.mqtt.verify_payload_match(key="mqtt_msg", pattern=r"^on$")

    col.messaging.ssh.measure_stdout(ssh_id=1, command="cat /etc/version", key="uut_version")


if __name__ == "__main__":
    main()
    col.endex()
