"""U-MSG-REDIS: Redis sim KV and pub/sub contract."""

from __future__ import annotations

from colosseum_messaging.redis.client import RedisClientWrapper
from colosseum_messaging.sim import sim_redis_clear


def test_sim_set_get_roundtrip() -> None:
    sim_redis_clear()
    client = RedisClientWrapper({"host": "127.0.0.1", "driver": "sim"})
    client.set("foo", "bar")
    assert client.get("foo") == "bar"


def test_sim_publish_receive_roundtrip() -> None:
    client = RedisClientWrapper({"host": "127.0.0.1", "port": 6379, "driver": "sim"})
    client.publish("events", "ping")
    msg = client.receive("events", timeout=0.5)
    assert msg == {"topic": "events", "payload": "ping"}
