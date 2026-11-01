from __future__ import annotations

import queue
import time
import uuid
from typing import TYPE_CHECKING

import paho.mqtt.client as mqtt
from colosseum.logging import get_logger

from colosseum_messaging._pump import PumpHandle, topic_payload
from colosseum_messaging.sim import SIM_MAILBOX

if TYPE_CHECKING:
    from collections.abc import Mapping

    from colosseum_messaging._pump import Hook

_logger = get_logger("colosseum.messaging.mqtt")
_ALLOWED_DRIVERS = frozenset({"sim", "mqtt"})


class MqttClientWrapper:
    def __init__(self, config: Mapping[str, object]) -> None:
        self._host = str(config["host"])
        self._port = int(str(config.get("port", 1883)))
        self._topic = str(config.get("topic", "#"))
        driver = str(config.get("driver", "mqtt")).lower()
        if driver not in _ALLOWED_DRIVERS:
            raise ValueError(
                f"messaging.mqtt driver must be one of {sorted(_ALLOWED_DRIVERS)}, got {driver!r}",
            )
        self._sim = driver == "sim"
        self._mailbox_key = f"mqtt:{self._host}:{self._port}"
        self._client: mqtt.Client | None = None
        self._incoming: queue.Queue[tuple[str, str]] = queue.Queue()
        self._subscribed_topic: str | None = None
        self._listen_pump = PumpHandle()
        self._send_pump = PumpHandle()
        if self._sim:
            _logger.debug("MQTT client sim mode host=%s", self._host)
            return
        client_id = str(config.get("client_id") or f"colosseum-{uuid.uuid4().hex[:8]}")
        callback_api = mqtt.CallbackAPIVersion.VERSION2  # type: ignore[attr-defined]
        self._client = mqtt.Client(
            callback_api_version=callback_api,
            client_id=client_id,
        )
        username = config.get("username")
        password = config.get("password")
        if username is not None:
            self._client.username_pw_set(
                str(username),
                None if password is None else str(password),
            )
        self._client.on_message = self._on_message
        keepalive = int(str(config.get("keepalive", 60)))
        self._client.connect(self._host, self._port, keepalive=keepalive)
        self._client.loop_start()

    def _on_message(
        self,
        _client: mqtt.Client,
        _userdata: object,
        message: mqtt.MQTTMessage,
    ) -> None:
        topic = str(message.topic)
        payload = message.payload.decode("utf-8", errors="replace")
        self._incoming.put((topic, payload))

    def publish(self, topic: str, payload: str) -> None:
        if self._send_pump.running():
            raise RuntimeError("MQTT send pump owns this client")
        self._publish(topic, payload)

    def _publish(self, topic: str, payload: str) -> None:
        _logger.debug("MQTT PUBLISH %s", topic)
        if self._sim:
            SIM_MAILBOX.publish(self._mailbox_key, topic, payload)
            return
        if self._client is None:
            raise RuntimeError("MQTT client is not connected")
        result = self._client.publish(topic, payload)
        status = result[0] if isinstance(result, tuple) else result.rc
        if status != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish failed with rc={status}")

    def receive(self, timeout: float = 1.0, topic: str | None = None) -> dict[str, str]:
        if self._listen_pump.running():
            raise RuntimeError("MQTT listen pump owns this client")
        return self._receive(timeout, topic)

    def _receive(self, timeout: float = 1.0, topic: str | None = None) -> dict[str, str]:
        subscribe_topic = self._topic if topic is None else topic
        _logger.debug("MQTT RECEIVE topic=%s timeout=%ss", subscribe_topic, timeout)
        if self._sim:
            deadline = time.monotonic() + timeout
            while True:
                remaining = max(0.0, deadline - time.monotonic())
                item = SIM_MAILBOX.receive(self._mailbox_key, remaining)
                if item is None:
                    raise TimeoutError(
                        f"No MQTT message on {subscribe_topic!r} within {timeout}s",
                    )
                msg_topic, payload = item
                if _topic_matches(subscribe_topic, msg_topic):
                    return {"topic": msg_topic, "payload": payload}
                if remaining <= 0:
                    raise TimeoutError(
                        f"No MQTT message on {subscribe_topic!r} within {timeout}s",
                    )

        if self._client is None:
            raise RuntimeError("MQTT client is not connected")
        if self._subscribed_topic != subscribe_topic:
            if self._subscribed_topic is not None:
                self._client.unsubscribe(self._subscribed_topic)
            result, _mid = self._client.subscribe(subscribe_topic)
            if result != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT subscribe failed with rc={result}")
            self._subscribed_topic = subscribe_topic

        deadline = time.monotonic() + timeout
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0:
                raise TimeoutError(
                    f"No MQTT message on {subscribe_topic!r} within {timeout}s",
                )
            try:
                msg_topic, payload = self._incoming.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(
                    f"No MQTT message on {subscribe_topic!r} within {timeout}s",
                ) from exc
            if _topic_matches(subscribe_topic, msg_topic):
                return {"topic": msg_topic, "payload": payload}

    def start_listen(self, on_message: Hook, topic: str | None = None) -> None:
        def poll(timeout: float) -> dict[str, str] | None:
            return self._receive(timeout, topic)

        self._listen_pump.start(poll=poll, on_message=on_message, name="mqtt-listen")

    def stop_listen(self) -> None:
        self._listen_pump.stop()

    def start_sender(self) -> None:
        self._send_pump.start(offer=self._offer_send, name="mqtt-send")

    def enqueue(self, topic: str, payload: str) -> None:
        self._send_pump.submit((topic, payload))

    def stop_sender(self) -> None:
        self._send_pump.stop()

    def _offer_send(self, item: object) -> None:
        topic, payload = topic_payload(item)
        self._publish(topic, payload)

    def close(self) -> None:
        self.stop_listen()
        self.stop_sender()
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                _logger.exception("Failed to close MQTT client")
            self._client = None
            self._subscribed_topic = None


def _topic_matches(filter_topic: str, message_topic: str) -> bool:
    return mqtt.topic_matches_sub(filter_topic, message_topic)
