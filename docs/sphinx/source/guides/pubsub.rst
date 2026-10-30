Live Redis, ZMQ and MQTT
========================

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

Continuous pub/sub
------------------

``listen`` leaves a subscriber thread running. Each message it takes off the
socket is a ``messaging`` measurement, command ``zmq.listen``, ``mqtt.listen``,
or ``redis.listen``, with value ``{"topic", "payload"}``. ``fail_pattern``
sets that row to ``FAIL`` when the payload matches and ``PASS`` otherwise.
``stop_listen`` joins the thread and drains the write queue. ``verify_listen``
reads those rows: ``max_silence_s`` is the longest gap between stored
timestamps after the first message, and ``min_received`` requires that many
device rows. One-shot ``send`` / ``receive`` / ``verify_payload_match`` remain
the calls for a single message.

ZMQ PUB and SUB are different configured ids. The listen thread owns the SUB
socket, and the send thread owns the PUB socket::

   col.messaging.zmq.listen(
       zmq_id=2, key="status", fail_pattern=r"\b(ERR|FAULT|offline)\b",
   )
   # stimulate the unit while the listen thread records each broadcast
   col.messaging.zmq.stop_listen(zmq_id=2, key="status")
   col.messaging.zmq.verify_listen(key="status", max_silence_s=0.5, min_received=1)

   col.messaging.zmq.start_sender(zmq_id=1)
   col.messaging.zmq.enqueue(zmq_id=1, payload="arm", topic="cmd")
   col.messaging.zmq.stop_sender(zmq_id=1)

MQTT and Redis use the same sequence of listen, stop, and verify calls. MQTT ``publish``
and Redis ``publish`` stay callable from the test thread while ``listen`` is
running. ``start_sender`` is the queued path::

   col.messaging.mqtt.listen(
       mqtt_id=1, key="status", topic="device/#",
       fail_pattern=r"\b(ERR|FAULT|offline)\b",
   )
   col.messaging.mqtt.stop_listen(mqtt_id=1, key="mqtt_status")
   col.messaging.mqtt.verify_listen(key="mqtt_status", max_silence_s=0.5, min_received=1)

   col.messaging.redis.listen(
       redis_id=1, channel="events", key="mqtt_status",
       fail_pattern=r"\b(ERR|FAULT|offline)\b",
   )
   col.messaging.redis.stop_listen(redis_id=1, key="redis_status")
   col.messaging.redis.verify_listen(key="redis_status", min_received=1)


Establish readiness before testing delivery
-------------------------------------------

MQTT's ``listen`` starts a worker; its return is not a SUBACK barrier. With a
live broker and the MQTT row above, use a probe topic included by the listener,
confirm a probe was received, and only then stimulate the DUT::

   import time
   from threading import Event

   ready = Event()
   def on_probe(message):
       if message["payload"] == "probe":
           ready.set()

   col.messaging.mqtt.listen(mqtt_id=1, key="mqtt_ready", topic="docs/ready", on_message=on_probe)
   try:
       deadline = time.monotonic() + 5.0
       while True:
           col.messaging.mqtt.publish(mqtt_id=1, topic="docs/ready", payload="probe")
           if ready.wait(0.1):
               break
           if time.monotonic() >= deadline:
               raise TimeoutError("MQTT subscription did not receive a readiness probe")
       # The subscription is now demonstrated ready for this topic.
       # Trigger the DUT and check its messages under a separate evidence key.
   finally:
       col.messaging.mqtt.stop_listen(mqtt_id=1, key="mqtt_ready")

This is a live-fixture recipe, not a simulated guarantee of broker timing.
Do not count probe traffic as DUT acceptance evidence. For a real DUT listener,
use a separate readiness topic/connection or distinguish probe payloads.

For ZMQ, configure the PUB/SUB rows above. In another procedure with ``time``
and ``Event`` imported, demonstrate the subscription before a one-shot stimulus::

   ready = Event()
   def on_probe(message):
       if message["payload"] == "ready-probe":
           ready.set()

   col.messaging.zmq.listen(zmq_id=2, key="zmq_ready", on_message=on_probe)
   col.messaging.zmq.start_sender(zmq_id=1)
   try:
       deadline = time.monotonic() + 5.0
       while True:
           col.messaging.zmq.enqueue(zmq_id=1, topic="events", payload="ready-probe")
           if ready.wait(0.1):
               break
           if time.monotonic() >= deadline:
               raise TimeoutError("ZMQ subscription did not receive a readiness probe")
       # Only now trigger the one-shot stimulus under test.
   finally:
       col.messaging.zmq.stop_sender(zmq_id=1)
       col.messaging.zmq.stop_listen(zmq_id=2, key="zmq_ready")

The sender owns the PUB socket and the listener owns the SUB socket. A fixed
sleep is not proof of subscription propagation. Exclude readiness probes from
DUT acceptance evidence and use distinct keys for later acquisitions.

An external fixture that reports MQTT SUBACK or ZMQ subscription readiness can
provide a stronger barrier. Redis similarly needs an established subscription
before a one-shot publication. See :doc:`/api/mqtt`, :doc:`/api/zmq`,
:doc:`/api/redis`, and :doc:`/config_reference` for exact call arguments.
