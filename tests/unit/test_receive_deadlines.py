"""Redis receive deadlines and simulated topic filters."""

from __future__ import annotations

import pytest
from colosseum_messaging.mqtt.client import MqttClientWrapper
from colosseum_messaging.redis.client import RedisClientWrapper
from colosseum_messaging.zmq.client import ZmqClientWrapper


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


class _PubSub:
    def __init__(self, clock: _Clock, messages: list[dict[str, object] | None]) -> None:
        self.clock = clock
        self.messages = list(messages)
        self.requested: list[float] = []

    def subscribe(self, _channel: str) -> None:
        return None

    def get_message(self, timeout: float) -> dict[str, object] | None:
        self.requested.append(timeout)
        if self.messages:
            item = self.messages.pop(0)
            if item is None:
                self.clock.now += timeout
            return item
        self.clock.now += timeout
        return None


def _redis(
    monkeypatch: pytest.MonkeyPatch, pubsub: _PubSub, *, subscribed: bool,
) -> RedisClientWrapper:
    monkeypatch.setattr("colosseum_messaging.redis.client.time.monotonic", pubsub.clock.monotonic)
    client = RedisClientWrapper.__new__(RedisClientWrapper)
    client._sim = False
    client._client = object()
    client._pubsub = pubsub if subscribed else None
    client._subscribed_channel = "events" if subscribed else None
    return client


def test_redis_receive_skips_subscription_acknowledgement(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    pubsub = _PubSub(
        clock,
        [{"type": "subscribe", "data": 1}, {"type": "message", "data": "ping"}],
    )

    class _Conn:
        def pubsub(self, *, ignore_subscribe_messages: bool = True) -> _PubSub:
            return pubsub

    monkeypatch.setattr("colosseum_messaging.redis.client.time.monotonic", clock.monotonic)
    client = RedisClientWrapper.__new__(RedisClientWrapper)
    client._sim = False
    client._client = _Conn()
    client._pubsub = None
    client._subscribed_channel = None
    message = client.receive("events", timeout=1.0)
    assert message == {"topic": "events", "payload": "ping"}
    assert pubsub.requested[0] == pytest.approx(1.0)


def test_redis_receive_empty_channel_uses_one_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    pubsub = _PubSub(clock, [])
    client = _redis(monkeypatch, pubsub, subscribed=True)
    with pytest.raises(TimeoutError, match="events"):
        client.receive("events", timeout=1.0)
    assert sum(pubsub.requested) == pytest.approx(1.0, abs=0.05)


def test_redis_receive_accepts_message_near_the_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()

    class _Late(_PubSub):
        def get_message(self, timeout: float) -> dict[str, object] | None:
            self.requested.append(timeout)
            if len(self.requested) == 1:
                self.clock.now += 0.85
                return None
            return {"type": "message", "data": "near"}

    pubsub = _Late(clock, [])
    client = _redis(monkeypatch, pubsub, subscribed=True)
    message = client.receive("events", timeout=1.0)
    assert message["payload"] == "near"
    assert pubsub.requested[0] == pytest.approx(1.0, abs=0.02)
    assert pubsub.requested[1] == pytest.approx(0.15, abs=0.02)


def test_mqtt_sim_uses_configured_topic_when_override_is_omitted() -> None:
    client = MqttClientWrapper(
        {"host": "wanted.invalid", "port": 1883, "topic": "wanted/#", "driver": "sim"},
    )
    client.publish("unrelated/status", "nope")
    client.publish("wanted/status", "yes")
    message = client.receive(timeout=0.5)
    assert message == {"topic": "wanted/status", "payload": "yes"}


def test_mqtt_sim_times_out_when_nothing_matches_the_configured_topic() -> None:
    client = MqttClientWrapper(
        {"host": "empty.invalid", "port": 1883, "topic": "wanted/#", "driver": "sim"},
    )
    client.publish("unrelated/status", "nope")
    with pytest.raises(TimeoutError):
        client.receive(timeout=0.2)


def test_zmq_sim_skips_topics_outside_the_subscription() -> None:
    endpoint = "inproc://wanted-filter"
    pub = ZmqClientWrapper({"endpoint": endpoint, "socket": "pub", "driver": "sim"})
    sub = ZmqClientWrapper(
        {"endpoint": endpoint, "socket": "sub", "topic": "wanted", "driver": "sim"},
    )
    pub.send("nope", topic="unrelated")
    pub.send("yes", topic="wanted")
    assert sub.receive(timeout=0.5) == {"topic": "wanted", "payload": "yes"}


def test_zmq_sim_times_out_on_only_nonmatching_topics() -> None:
    endpoint = "inproc://wanted-empty"
    pub = ZmqClientWrapper({"endpoint": endpoint, "socket": "pub", "driver": "sim"})
    sub = ZmqClientWrapper(
        {"endpoint": endpoint, "socket": "sub", "topic": "wanted", "driver": "sim"},
    )
    pub.send("nope", topic="unrelated")
    with pytest.raises(TimeoutError):
        sub.receive(timeout=0.2)
