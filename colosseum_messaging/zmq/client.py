from __future__ import annotations

import logging
from collections.abc import Mapping

import zmq
from colosseum_messaging.sim import SIM_MAILBOX

_logger = logging.getLogger("colosseum.messaging.zmq")


class ZmqClientWrapper:
    def __init__(self, config: Mapping[str, object]) -> None:
        self._config = dict(config)
        self._endpoint = str(config["endpoint"])
        self._socket_kind = str(config["socket"]).strip().lower()
        if self._socket_kind not in ("pub", "sub"):
            raise ValueError(
                f"messaging.zmq socket must be 'pub' or 'sub', got {self._socket_kind!r}"
            )
        self._topic = str(config.get("topic", ""))
        mode = config.get("mode")
        if mode is None:
            self._mode = "bind" if self._socket_kind == "pub" else "connect"
        else:
            self._mode = str(mode).strip().lower()
            if self._mode not in ("bind", "connect"):
                raise ValueError(
                    f"messaging.zmq mode must be 'bind' or 'connect', got {self._mode!r}"
                )
        self._sim = str(config.get("driver", "zmq")).lower() == "sim"
        self._context: zmq.Context[zmq.Socket[bytes]] | None = None
        self._socket: zmq.Socket[bytes] | None = None
        if self._sim:
            _logger.debug(
                "ZMQ client sim mode endpoint=%s socket=%s", self._endpoint, self._socket_kind
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
        if self._socket_kind != "sub":
            raise RuntimeError("ZMQ receive requires socket='sub'")
        _logger.debug("ZMQ RECEIVE endpoint=%s timeout=%ss", self._endpoint, timeout)
        if self._sim:
            item = SIM_MAILBOX.receive(self._endpoint, timeout)
            if item is None:
                raise TimeoutError(f"No ZMQ message on {self._endpoint!r} within {timeout}s")
            topic, payload = item
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

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close(linger=0)
            except Exception:
                _logger.exception("Failed to close ZMQ socket")
            self._socket = None
