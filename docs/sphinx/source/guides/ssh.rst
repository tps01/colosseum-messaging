SSH connection and execution
============================

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

.. warning::

   ``auth="auto"`` accepts previously unseen SSH host keys. A ``known_hosts``
   file is not an enrollment barrier in this mode: unknown keys are added.
   Pre-enroll the expected key through a trusted channel when server identity
   must be checked on the first connection. The plugin does not currently offer
   a strict-key policy with ordinary password/key authentication; ``auth="none"``
   rejects unknown keys but also requires the server's none-auth support.

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


See :doc:`/api/ssh` for ``start`` / ``collect`` and their recorded evidence,
:doc:`transfers` for SFTP/SCP, and :doc:`/config_reference` for connection keys.
The ``timeout`` in TOML bounds connection phases; the call's ``timeout=``
bounds command execution or collection. A completed nonzero exit requires an
explicit ``verify_exit`` check to fail acceptance.
