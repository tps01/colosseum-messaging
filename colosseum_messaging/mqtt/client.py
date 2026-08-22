from __future__ import annotations

import queue
import time
import uuid
from collections.abc import Mapping

import paho.mqtt.client as mqtt
from colosseum.logging import get_logger

from colosseum_messaging.sim import SIM_MAILBOX

_logger = get_logger("colosseum.messaging.mqtt")


class MqttClientWrapper:
    def __init__(self, config: Mapping[str, object]) -> None:
        self._config = dict(config)
        self._host = str(config["host"])
        self._port = int(str(config.get("port", 1883)))
        self._topic = str(config.get("topic", "#"))
        self._sim = str(config.get("driver", "mqtt")).lower() == "sim"
        self._mailbox_key = f"mqtt:{self._host}:{self._port}"
        self._client: mqtt.Client | None = None
        self._incoming: queue.Queue[tuple[str, str]] = queue.Queue()
        self._subscribed = False
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
        subscribe_topic = self._topic if topic is None else topic
        _logger.debug("MQTT RECEIVE topic=%s timeout=%ss", subscribe_topic, timeout)
        if self._sim:
            deadline = time.monotonic() + timeout
            while True:
                remaining = max(0.0, deadline - time.monotonic())
                item = SIM_MAILBOX.receive(self._mailbox_key, remaining)
                if item is None:
                    raise TimeoutError(
                        f"No MQTT message on {subscribe_topic!r} within {timeout}s"
                    )
                msg_topic, payload = item
                if topic is None or _topic_matches(subscribe_topic, msg_topic):
                    return {"topic": msg_topic, "payload": payload}
                if remaining <= 0:
                    raise TimeoutError(
                        f"No MQTT message on {subscribe_topic!r} within {timeout}s"
                    )

        if self._client is None:
            raise RuntimeError("MQTT client is not connected")
        if not self._subscribed:
            result, _mid = self._client.subscribe(subscribe_topic)
            if result != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT subscribe failed with rc={result}")
            self._subscribed = True
        try:
            msg_topic, payload = self._incoming.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError(
                f"No MQTT message on {subscribe_topic!r} within {timeout}s"
            ) from exc
        return {"topic": msg_topic, "payload": payload}

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                _logger.exception("Failed to close MQTT client")
            self._client = None


def _topic_matches(filter_topic: str, message_topic: str) -> bool:
    if filter_topic in ("#", ""):
        return True
    filter_parts = filter_topic.split("/")
    message_parts = message_topic.split("/")
    for index, part in enumerate(filter_parts):
        if part == "#":
            return True
        if index >= len(message_parts):
            return False
        if part == "+":
            continue
        if part != message_parts[index]:
            return False
    return len(filter_parts) == len(message_parts)
