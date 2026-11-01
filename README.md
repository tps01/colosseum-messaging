# Colosseum Messaging

## Documentation

API reference (GitHub Pages): <https://tps01.github.io/colosseum-messaging/>

Framework hub: <https://tps01.github.io/colosseum-core/>

First-party Colosseum plugin providing `col.messaging.*` (HTTP, Redis, ZMQ,
MQTT, SSH, SCP).

## Install

Download the wheel from [GitHub Releases](https://github.com/tps01/colosseum-messaging/releases)
and install it in the same environment as core. Replace `<version>` with
the downloaded filename. For development, use
`python -m pip install -r requirements.txt`.

```bash
python -m pip install "./colosseum_messaging-<version>-py3-none-any.whl"
```

This installs the complete plugin (HTTP via stdlib, Redis, ZMQ, MQTT, SSH, and
SCP). It requires `colosseum-core` `>=0.18,<0.19` and registers the `messaging`
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

`auth = "auto"` (the default) accepts first-seen SSH host keys automatically
and also connects to known hosts. An explicit `known_hosts` file stores newly
accepted keys. `auth = "none"` keeps the existing requirement for trusted keys.

## Usage

```python
import colosseum as col

col.config.load_config("examples/configs/config.messaging.sim.toml")
col.messaging.http.get(http_id=1, path="/health", key="health")
col.messaging.http.verify_status(key="health", expected=200)
col.messaging.redis.set(redis_id=1, name="foo", value="bar")
col.messaging.redis.get(redis_id=1, name="foo", key="foo")
col.messaging.ssh.measure_stdout(ssh_id=1, command="cat /etc/version", key="uut_version")
col.messaging.ssh.verify_stdout_match(key="uut_version", pattern=r"v1\.2\.3")
col.messaging.ssh.exec(ssh_id=1, command="echo ok", key="exec_ok")
col.messaging.ssh.verify_exit(key="exec_ok", expected=0)
col.messaging.ssh.get(ssh_id=1, remote="/etc/network/interfaces", local="interfaces", key="iface")
col.messaging.scp.get(ssh_id=1, remote="/etc/network/interfaces", local="iface_scp", key="iface_scp")
col.endex()
```

## Results

The plugin uses Colosseum's standard run artifacts. See the
[core output guide](https://tps01.github.io/colosseum-core/guides/output_artifacts.html)
for summaries, evidence queries, and opt-in reports.

## Develop

```bash
pip install -e ../colosseum-core
pip install -r requirements.txt
pytest
ruff check .
mypy
```

SSH connection setup defaults to three total attempts with a 10-second timeout
per connection phase. Pass `retries=` to SSH operations to override the attempt
count (`0` or `1` makes one attempt). The SSH config row's `timeout` overrides
the connection timeout; command `timeout=` is independent. Only connection setup
is retried; remote operations are never replayed.
