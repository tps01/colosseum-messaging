# Colosseum Messaging

## Documentation

API reference (GitHub Pages): https://tps01.github.io/colosseum-messaging/

Framework hub: https://tps01.github.io/colosseum-core/

First-party Colosseum plugin providing `col.messaging.*` (HTTP, Redis, ZMQ,
MQTT, SSH, SCP).

## Install

Download the wheel from [GitHub Releases](https://github.com/tps01/colosseum-messaging/releases)
and install it in the same environment as core. Replace `<version>` with
the downloaded filename. For development, use `python -m pip install -e .`.

```bash
python -m pip install "./colosseum_messaging-<version>-py3-none-any.whl"
```

This installs the complete plugin (HTTP via stdlib, Redis, ZMQ, MQTT, SSH, and
SCP). It requires `colosseum-core` `>=0.17.0,<0.18` and registers the `messaging`
namespace through the `colosseum.plugins` entry point.

HTTP uses the Python standard library (`http.client`) so the default install
stays on the project license allowlist. Third-party clients: `redis` (MIT),
`pyzmq` (BSD-3; bundled libzmq is LGPL unmodified), `paho-mqtt` under
**EDL-1.0** (BSD-3 equivalent; dual-licensed EPL-2.0 OR EDL-1.0), and
`paramiko` and `scp` (LGPL unmodified).

## SSH platform

SSH is Linux-first. Path/glob helpers still accept Windows-style remote paths
when `platform = "windows"` is set in `[messaging.ssh]`. Shell defaults for
`exec_sequence` without `interpreter=` assume a POSIX host; on Windows, pass
`interpreter=` or use an explicit `.bat`/`.cmd`/`.ps1` script. Unsupported
defaults raise `colosseum_messaging.exceptions.MessagingCapabilityError`.

## Usage

```python
import colosseum as col

col.config.load_config("examples/configs/config.messaging.sim.toml")
col.messaging.http.get(http_id=1, path="/health", key="health")
col.messaging.http.verify_status(key="health", expected=200)
col.messaging.redis.set(redis_id=1, name="foo", value="bar")
col.messaging.redis.get(redis_id=1, name="foo", key="foo")
col.messaging.ssh.measure_stdout(ssh_id=1, command="uname -a", key="uname")
col.messaging.ssh.verify_stdout_match(key="uname", pattern=r"Linux")
col.messaging.ssh.exec(ssh_id=1, command="echo ok", key="exec_ok")
col.messaging.ssh.verify_exit(key="exec_ok", expected=0)
col.messaging.ssh.get(ssh_id=1, remote="/etc/network/interfaces", local="interfaces", key="iface")
col.messaging.scp.get(ssh_id=1, remote="/etc/network/interfaces", local="iface_scp", key="iface_scp")
col.endex()
```

## Expected artifacts

Normal CLI runs write `summary.json`, `summary.txt`, `execution.sqlite`, and
`debug.log` under the run output directory. Reports are opt-in: add
`--report wats` to the run command to write `wats_<datetime>_<script>.json`,
or `--report junit` for `junit.xml`. Loading `metadata.yaml` enriches an
enabled report; it does not enable reporting. See the
[core reporting guide](https://tps01.github.io/colosseum-core/guides/output_artifacts.html).

## Develop

```bash
pip install -e ../colosseum-core
pip install -e .
pytest
ruff check .
mypy
```
