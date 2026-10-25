from __future__ import annotations

import time
from typing import TYPE_CHECKING

from colosseum.logging import get_logger

import zmq
from colosseum_messaging._pump import PumpHandle, topic_payload
from colosseum_messaging.sim import SIM_MAILBOX

if TYPE_CHECKING:
    from collections.abc import Mapping

    from colosseum_messaging._pump import Hook

_logger = get_logger("colosseum.messaging.zmq")
_ALLOWED_DRIVERS = frozenset({"sim", "zmq"})


class ZmqClientWrapper:
    def __init__(self, config: Mapping[str, object]) -> None:
        self._endpoint = str(config["endpoint"])
        self._socket_kind = str(config["socket"]).strip().lower()
        if self._socket_kind not in ("pub", "sub"):
            raise ValueError(
                f"messaging.zmq socket must be 'pub' or 'sub', got {self._socket_kind!r}",
            )
        self._topic = str(config.get("topic", ""))
        mode = config.get("mode")
        if mode is None:
            self._mode = "bind" if self._socket_kind == "pub" else "connect"
        else:
            self._mode = str(mode).strip().lower()
            if self._mode not in ("bind", "connect"):
                raise ValueError(
                    f"messaging.zmq mode must be 'bind' or 'connect', got {self._mode!r}",
                )
        driver = str(config.get("driver", "zmq")).lower()
        if driver not in _ALLOWED_DRIVERS:
            raise ValueError(
                f"messaging.zmq driver must be one of {sorted(_ALLOWED_DRIVERS)}, got {driver!r}",
            )
        self._sim = driver == "sim"
        self._context: zmq.Context[zmq.Socket[bytes]] | None = None
        self._socket: zmq.Socket[bytes] | None = None
        self._listen_pump = PumpHandle()
        self._send_pump = PumpHandle()
        if self._sim:
            _logger.debug(
                "ZMQ client sim mode endpoint=%s socket=%s", self._endpoint, self._socket_kind,
            )
            return
        self._context = zmq.Context.instance()
        if self._socket_kind == "pub":
            self._socket = self._context.socket(zmq.PUB)
        else:
            self._socket = self._context.socket(zmq.SUB)
            self._socket.setsockopt_string(zmq.SUBSCRIBE, self._topic)
        if self._mode == "bind":
            self._socket.bind(self._endpoint)
        else:
            self._socket.connect(self._endpoint)

    def send(self, payload: str, topic: str = "") -> None:
        if self._pump_owns_socket():
            raise RuntimeError("ZMQ pump owns this socket")
        self._send(payload, topic)

    def _send(self, payload: str, topic: str = "") -> None:
        if self._socket_kind != "pub":
            raise RuntimeError("ZMQ send requires socket='pub'")
        topic_s = topic if topic else self._topic
        _logger.debug("ZMQ SEND endpoint=%s topic=%r", self._endpoint, topic_s)
        if self._sim:
            SIM_MAILBOX.publish(self._endpoint, topic_s, payload)
            return
        if self._socket is None:
            raise RuntimeError("ZMQ socket is not connected")
        if topic_s:
            self._socket.send_multipart([topic_s.encode("utf-8"), payload.encode("utf-8")])
        else:
            self._socket.send_string(payload)

    def receive(self, timeout: float = 1.0) -> dict[str, str]:
        if self._pump_owns_socket():
            raise RuntimeError("ZMQ pump owns this socket")
        return self._receive(timeout)

    def _receive(self, timeout: float = 1.0) -> dict[str, str]:
        if self._socket_kind != "sub":
            raise RuntimeError("ZMQ receive requires socket='sub'")
        _logger.debug("ZMQ RECEIVE endpoint=%s timeout=%ss", self._endpoint, timeout)
        if self._sim:
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"No ZMQ message on {self._endpoint!r} within {timeout}s",
                    )
                item = SIM_MAILBOX.receive(self._endpoint, remaining)
                if item is None:
                    raise TimeoutError(
                        f"No ZMQ message on {self._endpoint!r} within {timeout}s",
                    )
                topic, payload = item
                if topic.startswith(self._topic):
                    return {"topic": topic, "payload": payload}
        if self._socket is None:
            raise RuntimeError("ZMQ socket is not connected")
        self._socket.setsockopt(zmq.RCVTIMEO, int(max(timeout, 0.0) * 1000))
        try:
            frames = self._socket.recv_multipart()
        except zmq.Again as exc:
            raise TimeoutError(f"No ZMQ message on {self._endpoint!r} within {timeout}s") from exc
        if len(frames) >= 2:
            topic = frames[0].decode("utf-8", errors="replace")
            payload = frames[1].decode("utf-8", errors="replace")
        else:
            topic = self._topic
            payload = frames[0].decode("utf-8", errors="replace") if frames else ""
        return {"topic": topic, "payload": payload}

    def start_listen(self, on_message: Hook) -> None:
        if self._socket_kind != "sub":
            raise RuntimeError("ZMQ listen requires socket='sub'")

        def poll(timeout: float) -> dict[str, str] | None:
            return self._receive(timeout)

        self._listen_pump.start(poll=poll, on_message=on_message, name="zmq-listen")

    def stop_listen(self) -> None:
        self._listen_pump.stop()

    def start_sender(self) -> None:
        if self._socket_kind != "pub":
            raise RuntimeError("ZMQ sender requires socket='pub'")
        self._send_pump.start(offer=self._offer_send, name="zmq-send")

    def enqueue(self, payload: str, topic: str = "") -> None:
        self._send_pump.submit((topic, payload))

    def stop_sender(self) -> None:
        self._send_pump.stop()

    def _offer_send(self, item: object) -> None:
        topic, payload = topic_payload(item)
        self._send(payload, topic)

    def _pump_owns_socket(self) -> bool:
        return self._listen_pump.running() or self._send_pump.running()

    def close(self) -> None:
        self.stop_listen()
        self.stop_sender()
        if self._socket is not None:
            try:
                self._socket.close(linger=0)
            except Exception:
                _logger.exception("Failed to close ZMQ socket")
            self._socket = None
