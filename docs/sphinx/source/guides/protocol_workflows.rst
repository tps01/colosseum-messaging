Messaging workflows
===================

Choose a workflow according to the endpoint you need:

* :doc:`http`: requests, response checks, and transport errors.
* :doc:`pubsub`: Redis, ZMQ, MQTT, continuous capture, and subscription readiness.
* :doc:`ssh`: host keys, connection setup, commands, and background collection.
* :doc:`transfers`: SFTP/SCP selection and saved-file evidence.

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


Failure categories
------------------

.. list-table::
   :header-rows: 1

   * - Event
     - Interpretation
   * - Connection refused, handshake failure, or broken transport
     - The operation cannot complete; normally ERROR and an exception.
   * - Completed HTTP error response or SSH nonzero exit
     - Recorded response/result; verify status or exit code explicitly.
   * - Response does not meet expected content
     - Verification FAIL; later steps continue.
   * - Receive or collection timeout
     - No completed result within the wait; do not interpret as an empty success.
   * - Listener/sender worker fails
     - Stop/join the worker and inspect its error. Starting a worker does not
       establish that its background work succeeded.

Optional behavior follows :doc:`api_conventions`. Normal CLI runs save
response evidence in ``execution.sqlite`` and failures in ``summary.txt``.
Downloads and SSH background stdout/stderr files are additional artifacts.
Contributor-only pump details are in :doc:`development`.
