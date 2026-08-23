# Colosseum Messaging

First-party Colosseum plugin providing `col.messaging.*` (HTTP, Redis, ZMQ, MQTT, SSH).

## Install

```bash
pip install colosseum-messaging
```

This installs the complete plugin (HTTP via stdlib, Redis, ZMQ, MQTT, and SSH). It requires
`colosseum-core` 0.15.x and registers the `messaging` namespace through the
`colosseum.plugins` entry point.

HTTP uses the Python standard library (`urllib.request`) so the default install stays on
the project license allowlist. Third-party clients: `redis` (MIT), `pyzmq` (BSD-3; bundled
libzmq is LGPL unmodified), `paho-mqtt` under **EDL-1.0** (BSD-3 equivalent; dual-licensed
EPL-2.0 OR EDL-1.0), and `paramiko` (LGPL unmodified).

## Usage

```python
import colosseum as col

col.config.load_config("examples/configs/bench.messaging.sim.toml")
col.messaging.http.get(http_id=1, path="/health", key="health")
col.messaging.http.verify_status(key="health", expected=200)
col.messaging.redis.set(redis_id=1, name="foo", value="bar")
col.messaging.redis.get(redis_id=1, name="foo", key="foo")
col.messaging.ssh.measure_stdout(ssh_id=1, command="uname -a", key="uname")
col.endex()
```

## Develop

```bash
pip install -e ../colosseum-core
pip install -e .
pytest
ruff check .
mypy
```
