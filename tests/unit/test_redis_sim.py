"""U-MSG-REDIS: Redis sim KV and pub/sub specification."""

from __future__ import annotations

from colosseum_messaging.redis.client import RedisClientWrapper
from colosseum_messaging.sim import sim_redis_clear


def test_sim_set_get_roundtrip() -> None:
    sim_redis_clear()
    client = RedisClientWrapper({"host": "127.0.0.1", "driver": "sim"})
    client.set("foo", "bar")
    assert client.get("foo") == "bar"


def test_sim_kv_isolated_by_db() -> None:
    sim_redis_clear()
    db0 = RedisClientWrapper({"host": "127.0.0.1", "driver": "sim", "db": 0})
    db1 = RedisClientWrapper({"host": "127.0.0.1", "driver": "sim", "db": 1})
    db0.set("foo", "bar")
    assert db1.get("foo") is None
    assert db0.get("foo") == "bar"


def test_sim_pubsub_shared_across_db() -> None:
    db0 = RedisClientWrapper({"host": "127.0.0.1", "port": 6379, "driver": "sim", "db": 0})
    db1 = RedisClientWrapper({"host": "127.0.0.1", "port": 6379, "driver": "sim", "db": 1})
    db0.publish("events", "ping")
    msg = db1.receive("events", timeout=0.5)
    assert msg == {"topic": "events", "payload": "ping"}


def test_sim_publish_receive_roundtrip() -> None:
    client = RedisClientWrapper({"host": "127.0.0.1", "port": 6379, "driver": "sim"})
    client.publish("events", "ping")
    msg = client.receive("events", timeout=0.5)
    assert msg == {"topic": "events", "payload": "ping"}
