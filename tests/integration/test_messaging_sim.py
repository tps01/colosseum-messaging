"""I-MSG: messaging HTTP/Redis/ZMQ/MQTT/SSH on sim."""

from __future__ import annotations

from pathlib import Path

import colosseum as col
import pytest
from colosseum.config import load_config


def test_messaging_send_receive_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = (
        Path(__file__).resolve().parents[2]
        / "examples"
        / "configs"
        / "config.messaging.sim.toml"
    )
    monkeypatch.chdir(tmp_path)
    load_config(config_path)

    col.messaging.http.get(http_id=1, path="/health", key="health")
    assert col.messaging.http.verify_status(key="health", expected=200).status == "PASS"
    assert col.messaging.http.verify_body_match(key="health", pattern=r"GET /health").status == (
        "PASS"
    )

    col.messaging.redis.set(redis_id=1, name="foo", value="bar")
    col.messaging.redis.get(redis_id=1, name="foo", key="foo")
    assert col.messaging.redis.verify_value_match(key="foo", pattern=r"^bar$").status == "PASS"
    col.messaging.redis.publish(redis_id=1, channel="events", message="ping")
    col.messaging.redis.receive(redis_id=1, channel="events", key="redis_evt")

    col.messaging.zmq.send(zmq_id=1, payload="hello", topic="t1")
    col.messaging.zmq.receive(zmq_id=2, key="zmq_msg")
    assert col.messaging.zmq.verify_payload_match(key="zmq_msg", pattern=r"hello").status == "PASS"

    col.messaging.mqtt.publish(mqtt_id=1, topic="device/cmd", payload="on")
    col.messaging.mqtt.receive(mqtt_id=1, key="mqtt_msg", topic="device/#")
    assert col.messaging.mqtt.verify_payload_match(key="mqtt_msg", pattern=r"^on$").status == "PASS"

    out = col.messaging.ssh.measure_stdout(
        ssh_id=1, command="cat /etc/version", key="uut_version",
    )
    assert "v1.2.3" in out

    result = col.messaging.ssh.exec(ssh_id=1, command="echo ok", key="exec_ok")
    assert result["stdout"] == "ok"
    assert col.messaging.ssh.verify_exit(key="exec_ok", expected=0).status == "PASS"
    assert col.messaging.ssh.verify_stdout_match(key="exec_ok", pattern=r"^ok$").status == "PASS"

    seq = col.messaging.ssh.exec_sequence(
        ssh_id=1,
        script="echo /tmp/*\n",
        key="seq",
    )
    assert "/tmp/*" in str(seq["stdout"])

    col.messaging.ssh.start(ssh_id=1, command="cat /etc/version", key="bg")
    collected = col.messaging.ssh.collect(ssh_id=1, key="bg")
    assert "v1.2.3" in str(collected["stdout"])

    with pytest.raises(SystemExit) as exc_info:
        col.endex()
    assert exc_info.value.code in (None, 0)
