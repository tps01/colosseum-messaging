"""ZMQ listen records every payload; verify_listen reads those rows."""

from __future__ import annotations

import time

import colosseum as col
import colosseum.context as context_module
import pytest
from colosseum.config import load_config
from colosseum.context import get_context, set_context
from colosseum_messaging import register


@pytest.fixture(autouse=True)
def _restore_context():
    try:
        previous = get_context()
    except RuntimeError:
        previous = None
    yield
    if previous is not None:
        set_context(previous)


def _open(tmp_path, port: int) -> None:
    config = tmp_path / "bench.toml"
    config.write_text(
        "\n".join(
            (
                "[[messaging.zmq]]",
                "zmq_id = 1",
                f'endpoint = "tcp://127.0.0.1:{port}"',
                'socket = "pub"',
                'driver = "sim"',
                "",
                "[[messaging.zmq]]",
                "zmq_id = 2",
                f'endpoint = "tcp://127.0.0.1:{port}"',
                'socket = "sub"',
                'topic = ""',
                'driver = "sim"',
                "",
            ),
        ),
        encoding="utf-8",
    )
    ctx = context_module.init_context(test_case_name=f"zmq_listen_{port}")
    ctx.output_dir = tmp_path
    ctx.db.initialize(tmp_path / "execution.sqlite")
    # Register messaging only. Loading every installed plugin pulls in optional
    # host dependencies this unit test does not use.
    register(ctx.plugin_registry)
    ctx.plugin_registry.loaded = True
    load_config(config)


def _rows(key: str):
    ctx = get_context()
    ctx.db.drain()
    return ctx.db.list_measurements("messaging", "zmq.listen", key)


def _wait_rows(key: str, count: int, *, device_only: bool = False):
    deadline = time.monotonic() + 2.0
    rows = []
    while time.monotonic() < deadline:
        rows = _rows(key)
        picked = [row for row in rows if row.status in {"PASS", "FAIL"}] if device_only else rows
        if len(picked) >= count:
            return rows
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {count} rows, saw {rows}")


def test_listen_records_each_payload_and_fails_a_match(tmp_path) -> None:
    _open(tmp_path, 5611)
    col.messaging.zmq.listen(zmq_id=2, key="status", fail_pattern=r"\bERR\b")
    try:
        with pytest.raises(RuntimeError, match="pump owns this socket"):
            col.messaging.zmq.receive(zmq_id=2, key="blocked", timeout=0.1)
        col.messaging.zmq.send(zmq_id=1, payload="ok", topic="t")
        col.messaging.zmq.send(zmq_id=1, payload="ERR 7", topic="t")
        col.messaging.zmq.send(zmq_id=1, payload="ok", topic="t")
        rows = _wait_rows("status", 3, device_only=True)
    finally:
        col.messaging.zmq.stop_listen(zmq_id=2, key="status")
    device = [row for row in rows if row.status in {"PASS", "FAIL"}]
    assert [row.status for row in device] == ["PASS", "FAIL", "PASS"]
    assert [row.value["payload"] for row in device] == ["ok", "ERR 7", "ok"]
    failed = col.messaging.zmq.verify_listen(key="status", min_received=1)
    assert failed.status == "FAIL"
    assert "matched" in failed.message


def test_verify_listen_passes_a_clean_stream(tmp_path) -> None:
    _open(tmp_path, 5612)
    col.messaging.zmq.listen(zmq_id=2, key="status", fail_pattern=r"\bERR\b")
    try:
        col.messaging.zmq.send(zmq_id=1, payload="ok", topic="t")
        col.messaging.zmq.send(zmq_id=1, payload="ok", topic="t")
        _wait_rows("status", 2, device_only=True)
    finally:
        col.messaging.zmq.stop_listen(zmq_id=2, key="status")
    result = col.messaging.zmq.verify_listen(
        key="status", max_silence_s=2.0, min_received=1,
    )
    assert result.status == "PASS"
    assert result.actual["received"] == 2
    assert result.actual["latest"] == "ok"


def test_verify_listen_fails_when_the_stream_goes_quiet(tmp_path) -> None:
    _open(tmp_path, 5613)
    col.messaging.zmq.listen(zmq_id=2, key="status")
    try:
        col.messaging.zmq.send(zmq_id=1, payload="tick", topic="t")
        _wait_rows("status", 1, device_only=True)
        time.sleep(0.3)
        col.messaging.zmq.send(zmq_id=1, payload="tock", topic="t")
        _wait_rows("status", 2, device_only=True)
    finally:
        col.messaging.zmq.stop_listen(zmq_id=2, key="status")
    result = col.messaging.zmq.verify_listen(key="status", max_silence_s=0.1, min_received=1)
    assert result.status == "FAIL"
    assert "max_gap_s" in result.message


def test_enqueue_delivers_to_the_subscriber(tmp_path) -> None:
    _open(tmp_path, 5614)
    col.messaging.zmq.start_sender(zmq_id=1)
    try:
        with pytest.raises(RuntimeError, match="pump owns this socket"):
            col.messaging.zmq.send(zmq_id=1, payload="direct", topic="cmd")
        col.messaging.zmq.enqueue(zmq_id=1, payload="arm", topic="cmd")
    finally:
        col.messaging.zmq.stop_sender(zmq_id=1)
    message = col.messaging.zmq.receive(zmq_id=2, key="cmd_msg", timeout=1.0)
    assert message == {"topic": "cmd", "payload": "arm"}


def test_hook_error_is_stored_beside_the_message(tmp_path) -> None:
    _open(tmp_path, 5615)

    def boom(_message: dict[str, str]) -> None:
        raise RuntimeError("hook failed")

    col.messaging.zmq.listen(zmq_id=2, key="status", on_message=boom)
    try:
        col.messaging.zmq.send(zmq_id=1, payload="ok", topic="t")
        rows = _wait_rows("status", 2)
    finally:
        col.messaging.zmq.stop_listen(zmq_id=2, key="status")
    assert [row.status for row in rows] == ["PASS", "ERROR"]
    assert rows[1].value["error"] == "hook failed"
    result = col.messaging.zmq.verify_listen(key="status", min_received=1)
    assert result.status == "FAIL"
    assert "errors" in result.message
