Getting started
===============

Install the ``colosseum-messaging`` wheel into the same virtual environment as
``colosseum-core``. Transports: HTTP, Redis, ZMQ, MQTT, SSH/SCP.

1. Config
---------

Save **config.messaging.sim.toml** beside your script (see ``examples/configs/config.messaging.sim.toml`` for all
transports)::

   [messaging.http]
   http_id = 1
   base_url = "http://127.0.0.1:8080"
   driver = "sim"

   [messaging.ssh]
   ssh_id = 1
   host = "127.0.0.1"
   username = "sim"
   driver = "sim"

Common keys (from each section's ``ConfigSectionSpec``): integer ``*_id``,
``driver`` (``sim`` or live), plus transport address fields (``base_url``,
``host``/``port``, ``endpoint``, ``topic``, …). SSH may also set ``platform``.

2. Procedure + verification
---------------------------

Save **msg_smoke.py** with this HTTP procedure::

   import colosseum as col

   def main() -> None:
       col.messaging.http.get(http_id=1, path="/health", key="health")
       col.messaging.http.verify_status(key="health", expected=200)

For SSH, add these calls inside the same ``main()``::

   col.messaging.ssh.measure_stdout(ssh_id=1, command="uname -a", key="uname")
   col.messaging.ssh.verify_stdout_match(key="uname", pattern=r".+")
   col.messaging.ssh.exec(ssh_id=1, command="echo ok", key="exec_ok")
   col.messaging.ssh.verify_exit(key="exec_ok", expected=0)

3. Run
------

::

   colosseum run msg_smoke.py -g config.messaging.sim.toml

Framework docs: `core hub <https://tps01.github.io/colosseum-core/>`__.

Expected: exit 0 with a PASS HTTP status check. Adding the SSH calls records
stdout and execution-result measurements and their checks. These are simulated
responses, not live authentication or network tests. See :doc:`http`,
:doc:`pubsub`, :doc:`ssh`, and :doc:`transfers` for live workflows.
