"""U-MSG-ZMQ: ZMQ sim pub/sub specification."""

from __future__ import annotations

from colosseum_messaging.zmq.client import ZmqClientWrapper


def test_sim_pub_sub_roundtrip() -> None:
    pub = ZmqClientWrapper(
        {"endpoint": "tcp://127.0.0.1:5555", "socket": "pub", "driver": "sim"},
    )
    sub = ZmqClientWrapper(
        {"endpoint": "tcp://127.0.0.1:5555", "socket": "sub", "driver": "sim"},
    )
    pub.send("hello", topic="t1")
    msg = sub.receive(timeout=0.5)
    assert msg == {"topic": "t1", "payload": "hello"}


def test_sim_publish_fans_out_to_each_subscriber() -> None:
    endpoint = "inproc://zmq-fanout"
    topic = "status"
    pub = ZmqClientWrapper(
        {"endpoint": endpoint, "socket": "pub", "topic": topic, "driver": "sim"},
    )
    sub_a = ZmqClientWrapper(
        {"endpoint": endpoint, "socket": "sub", "topic": topic, "driver": "sim"},
    )
    sub_b = ZmqClientWrapper(
        {"endpoint": endpoint, "socket": "sub", "topic": topic, "driver": "sim"},
    )
    pub.send("hello", topic=topic)
    assert sub_a.receive(timeout=0.5) == {"topic": topic, "payload": "hello"}
    assert sub_b.receive(timeout=0.5) == {"topic": topic, "payload": "hello"}
