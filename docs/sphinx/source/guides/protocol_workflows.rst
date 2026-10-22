Messaging workflows
===================

Offline smoke
-------------

Run from the repository root::

   colosseum run examples/test_messaging_sim.py -g examples/configs/config.messaging.sim.toml

This uses in-memory clients for HTTP, Redis, ZMQ, MQTT, SSH and SCP. Expected
exit: 0, with response/exec/download measurement rows and PASS verifications.
Background SSH creates stdout/stderr files, and SFTP/SCP downloads are saved
under the run directory. The simulator teaches API flow and does not validate
network timing, broker behavior, authentication or a real server.

.. literalinclude:: ../../../../examples/test_messaging_sim.py
   :language: python

HTTP requests and responses
---------------------------

``get``, ``post``, ``put``, ``delete`` and ``request`` return
``{"status_code": int, "body": str}``; ``body`` is decoded text, not parsed JSON.
``json=`` serializes a request body and supplies Content-Type unless overridden;
``data=`` supplies raw bytes/text instead. ``headers=`` and ``timeout=`` are
per-call arguments. The example POST includes all three.

For live HTTP, omit ``driver="sim"`` and configure::

   [messaging.http]
   http_id = 1
   base_url = "https://device.example/"
   timeout = 5.0
   verify_tls = true

Use ``verify_status`` and ``verify_body_match`` with the measurement key. An
HTTP error status is still a response to verify; transport failures raise an
error. A request timeout limits network operations, not a product's eventual
business completion. HTTP uses stdlib ``http.client``.

Live Redis, ZMQ and MQTT
------------------------

Each service needs its own installed/running endpoint; the plugin does not
start brokers. Example live sections (tailor addresses and credentials)::

   [messaging.redis]
   redis_id = 1
   host = "127.0.0.1"
   port = 6379
   db = 0
   timeout = 5.0

   [[messaging.zmq]]
   zmq_id = 1
   endpoint = "tcp://127.0.0.1:5555"
   socket = "pub"
   mode = "bind"

   [[messaging.zmq]]
   zmq_id = 2
   endpoint = "tcp://127.0.0.1:5555"
   socket = "sub"
   mode = "connect"
   topic = "events"

   [messaging.mqtt]
   mqtt_id = 1
   host = "127.0.0.1"
   port = 1883
   client_id = "colosseum-bench"
   topic = "device/status"

Redis can set ``username``/``password``; MQTT can set them and ``keepalive``.
Do not infer TLS/certificate configuration from the existence of credentials.
Live pub/sub delivery depends on connection and subscription readiness: a
simulator's immediate publish-then-receive sequence is not a synchronization
guarantee for a broker or a ZMQ pair. Arrange subscriber readiness in your
service fixture before the publish under test. A Redis missing key returns
``None``; a receive timeout is an error rather than a fabricated message.

SSH connection and execution
----------------------------

The same ``messaging.ssh`` row serves SSH, SFTP and SCP; there is no separate
``messaging.scp`` table. For a live lab host::

   [messaging.ssh]
   ssh_id = 1
   host = "bench.example"
   username = "test"
   auth = "auto"
   key_filename = "C:/bench/keys/id_ed25519"
   known_hosts = "C:/bench/keys/known_hosts"
   timeout = 10.0
   platform = "linux"

``auth="auto"`` (the default) connects to both known and first-seen hosts.
It uses Paramiko's ``AutoAddPolicy`` to accept new host keys automatically;
when ``known_hosts`` names a file, new keys are saved there (the file and its
parent directories are created when needed). Without an explicit
file, newly accepted keys are kept for the connection's lifetime. Existing
known keys are checked against the server's key.

``key_filename`` selects key authentication; otherwise a configured ``password``
disables agent/key discovery. Without either, Paramiko's normal agent/key lookup
applies. ``auth="none"`` is an explicit mode for hosts that support it and still
requires a trusted host key, not a fallback after failed authentication. Paths
in the config are process-relative unless absolute.

Connection setup makes up to three attempts by default. SSH calls that acquire
a connection accept ``retries=3``: this counts **total attempts**, including the
first. ``retries=1`` or ``retries=0`` makes one attempt; negative values and
non-integers are rejected. The row's ``timeout`` defaults to **10 seconds** and
bounds TCP connection, banner exchange and authentication separately in both
normal and ``auth="none"`` modes. Three TCP timeouts therefore take about 30
seconds; DNS and successive handshake phases can add time. Explicit row timeouts
are preserved. API ``timeout=`` continues to control command execution or job
collection independently.

Only connection establishment is retried. Authentication rejection, mismatched
known keys, untrusted keys in ``auth="none"`` mode, and invalid local
files/configuration fail immediately. Failed clients
are closed; successful clients are cached. A later call reuses the cached client
without reconnecting. Commands and file transfers are never replayed after an
operation starts, including when the connection drops.

In a CLI-managed ``main`` with that row loaded::

   col.messaging.ssh.exec(ssh_id=1, command="printf 'ready\\n'", timeout=5.0, key="ready")
   col.messaging.ssh.verify_exit(key="ready", expected=0)
   col.messaging.ssh.verify_stdout_match(key="ready", pattern=r"ready")
   col.messaging.ssh.exec_sequence(ssh_id=1, script="printf 'step1\\n'\nprintf 'step2\\n'\n", timeout=5.0, key="steps")
   col.messaging.ssh.verify_exit(key="steps", expected=0)

``exec`` / ``exec_sequence`` / ``collect`` record dictionaries with
``exit_code``, ``stdout`` and ``stderr``. ``measure_stdout`` instead records only
stripped stdout. ``exec`` accepts ``input=`` and ``get_pty=`` when the remote
program needs stdin or a terminal. Nonzero exit codes need ``verify_exit``;
successful transport execution alone does not establish product acceptance.

For background work, pair one start and collect with the same key::

   col.messaging.ssh.start(ssh_id=1, command="sleep 1; echo done", key="job", timeout=5.0)
   col.messaging.ssh.collect(ssh_id=1, key="job", timeout=10.0)
   col.messaging.ssh.verify_exit(key="job", expected=0)

``start`` creates ``ssh_job.stdout.txt`` and ``ssh_job.stderr.txt`` under the
active run directory and needs artifacts enabled. ``collect`` waits for the job
and records its result. Timeout exceptions should not be treated as completed
results. Do not assume an abandoned or timed-out job was stopped remotely.

Windows remote hosts use ``platform="windows"`` and Windows paths. For inline
PowerShell, supply an interpreter explicitly::

   col.messaging.ssh.exec_sequence(ssh_id=1, script="Write-Output ready\n", interpreter="powershell -NoProfile -NonInteractive -Command -", key="windows_steps")

For local ``path=`` scripts, ``.bat``/``.cmd`` use cmd, ``.ps1`` uses PowerShell,
and ``.sh``/``.bash`` use bash. An interpreter containing ``{remote}`` selects
upload-and-execute: the script is written under a writable remote temporary
directory, keeps its ``.ps1``, ``.bat``, or ``.cmd`` suffix, and is removed
after the command. The substituted path is quoted for the selected interpreter.
Otherwise the script is sent over stdin. Do not assume bare inline scripts get
POSIX shell semantics on Windows.

Transfer selection and evidence
-------------------------------

Prepare a local ``settings.json`` and a writable remote scratch directory before
using this live SFTP fragment::

   col.messaging.ssh.mkdir(ssh_id=1, path="/tmp/colosseum-example")
   col.messaging.ssh.put(ssh_id=1, local="settings.json", remote="/tmp/colosseum-example/settings.json")
   col.messaging.ssh.listdir(ssh_id=1, path="/tmp/colosseum-example", key="files")
   col.messaging.ssh.get(ssh_id=1, remote="/tmp/colosseum-example/*.json", local="sftp", newest=1, key="download")
   col.messaging.ssh.remove(ssh_id=1, path="/tmp/colosseum-example/settings.json")

``scp.put`` and ``scp.get`` offer the same transfer selection using ``ssh_id``;
live SCP requires the remote SCP program as well as SSH. Upload ``local`` paths
are local files. Download ``local`` paths resolve under the run output directory;
``get`` returns a list of saved local paths as measurement evidence. ``listdir``
records the remote name list. ``put``, ``mkdir`` and ``remove`` record command
outcomes. Use distinct keys for independent acquisitions.

Using the same prepared local file and remote scratch directory::

   col.messaging.scp.put(ssh_id=1, local="settings.json", remote="/tmp/colosseum-example/settings.json")
   col.messaging.scp.get(ssh_id=1, remote="/tmp/colosseum-example/settings.json", local="scp/settings.json", key="scp_download")

``recursive=True`` descends directories; ``max_depth`` bounds descent.
``newest`` / ``oldest`` select by remote modification time and are mutually
exclusive. Globs are resolved by the plugin, not a remote shell. A glob matches
file basenames throughout the selected tree and does not filter directory
names. Windows drive paths are accepted and matching is platform-aware. This
is selection of files, not a guarantee that a producer has finished writing
them.

Verification-only reuses recorded responses/results for row-based verifiers.
It does not contact a server to repeat skipped acquisitions, download missing
files, or recover background jobs. Keep downloaded files accessible if later
checks read their contents.
