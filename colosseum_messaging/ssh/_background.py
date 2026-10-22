"""Background SSH exec jobs."""

from __future__ import annotations

import select
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

# One channel window read. Readiness means some bytes are available, not this many.
_CHUNK_SIZE = 4096
_POLL_SECONDS = 0.05


class _ChannelReader(Protocol):
    channel: Any

    def read(self, size: int = -1) -> bytes: ...


class _DrainChannel(Protocol):
    def recv_ready(self) -> bool: ...

    def recv_stderr_ready(self) -> bool: ...

    def recv(self, nbytes: int) -> bytes: ...

    def recv_stderr(self, nbytes: int) -> bytes: ...

    def exit_status_ready(self) -> bool: ...

    def recv_exit_status(self) -> int: ...


@dataclass
class BackgroundJob:
    key: str
    command: str
    stdout_path: Path
    stderr_path: Path
    thread: threading.Thread | None
    channel: Any | None
    done: threading.Event = field(default_factory=threading.Event)
    exit_code: int | None = None
    error: BaseException | None = None
    # Set when collect gives up. A later channel close must not record success.
    abandoned: bool = False


def start_background_reader(
    *,
    stdout_path: Path,
    stderr_path: Path,
    stdout_file: _ChannelReader,
    stderr_file: _ChannelReader,
    on_complete: Callable[[int], None],
    on_error: Callable[[BaseException], None],
) -> threading.Thread:
    """Return an unstarted reader thread.

    The caller registers job state before calling ``Thread.start``. Completion
    is reported only with a harvested exit status; a reader exception is
    delivered to ``on_error`` instead of an invented success code.
    """

    def _append(path: Path, chunk: bytes) -> None:
        if not chunk:
            return
        with path.open("ab") as handle:
            handle.write(chunk)

    def _reader() -> None:
        try:
            stdout_path.write_bytes(b"")
            stderr_path.write_bytes(b"")
            code = _pump_channel(
                stdout_file.channel,
                stderr_file.channel,
                lambda chunk: _append(stdout_path, chunk),
                lambda chunk: _append(stderr_path, chunk),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            on_error(exc)
            return
        on_complete(code)

    return threading.Thread(target=_reader, daemon=True)


def drain_channel(
    stdout_file: _ChannelReader,
    stderr_file: _ChannelReader,
) -> tuple[bytes, bytes, int]:
    """Read both streams to completion and return stdout, stderr, and exit status."""
    stdout = bytearray()
    stderr = bytearray()
    code = _pump_channel(
        stdout_file.channel,
        stderr_file.channel,
        stdout.extend,
        stderr.extend,
    )
    return bytes(stdout), bytes(stderr), code


def _pump_channel(
    out_channel: _DrainChannel,
    err_channel: _DrainChannel,
    on_stdout: Callable[[bytes], None],
    on_stderr: Callable[[bytes], None],
) -> int:
    """Drain whichever stream is readable, using bounded channel receives.

    File-level ``read(n)`` waits until ``n`` bytes or EOF. A short stdout read
    can then sit forever while stderr fills the channel window. ``recv`` /
    ``recv_stderr`` return only the bytes already buffered.
    """
    while True:
        progressed = False
        if out_channel.recv_ready():
            chunk = out_channel.recv(_CHUNK_SIZE)
            if chunk:
                on_stdout(bytes(chunk))
                progressed = True
        if err_channel.recv_stderr_ready():
            chunk = err_channel.recv_stderr(_CHUNK_SIZE)
            if chunk:
                on_stderr(bytes(chunk))
                progressed = True
        stdout_pending = bool(out_channel.recv_ready())
        stderr_pending = bool(err_channel.recv_stderr_ready())
        if out_channel.exit_status_ready() and not stdout_pending and not stderr_pending:
            return int(out_channel.recv_exit_status())
        if progressed:
            continue
        _wait_for_activity(out_channel, _channel_timeout(out_channel))


def _channel_timeout(channel: _DrainChannel) -> float | None:
    getter = getattr(channel, "gettimeout", None)
    if not callable(getter):
        return None
    value = getter()
    if value is None:
        return None
    return float(value)


def _wait_for_activity(channel: _DrainChannel, timeout: float | None) -> None:
    """Block until the channel may be readable, or raise when ``timeout`` elapses."""
    waiter = getattr(channel, "wait_for_activity", None)
    if callable(waiter):
        if waiter(timeout) is False:
            raise TimeoutError("SSH channel timed out while draining output")
        return

    fileno = getattr(channel, "fileno", None)
    if callable(fileno):
        try:
            ready, _, _ = select.select([fileno()], [], [], timeout)
        except (OSError, ValueError, TypeError):
            ready = None
        else:
            if ready:
                return
            if timeout is not None:
                raise TimeoutError("SSH channel timed out while draining output")
            return

    pause = _POLL_SECONDS if timeout is None else min(_POLL_SECONDS, max(0.0, timeout))
    if pause:
        time.sleep(pause)
    if timeout is not None and pause >= timeout:
        raise TimeoutError("SSH channel timed out while draining output")
