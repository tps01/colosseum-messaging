"""Background SSH exec jobs."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


class _ChannelReader(Protocol):
    channel: Any

    def read(self, size: int = -1) -> bytes: ...


@dataclass
class BackgroundJob:
    key: str
    command: str
    stdout_path: Path
    stderr_path: Path
    thread: threading.Thread
    channel: Any | None
    done: threading.Event = field(default_factory=threading.Event)
    exit_code: int | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


def start_background_reader(
    *,
    stdout_path: Path,
    stderr_path: Path,
    stdout_file: _ChannelReader,
    stderr_file: _ChannelReader,
    on_complete: Callable[[int], None],
) -> threading.Thread:
    def _append(path: Path, chunk: bytes) -> None:
        if not chunk:
            return
        with path.open("ab") as handle:
            handle.write(chunk)

    def _reader() -> None:
        code = -1
        try:
            stdout_path.write_bytes(b"")
            stderr_path.write_bytes(b"")
            while not stdout_file.channel.exit_status_ready():
                if stdout_file.channel.recv_ready():
                    _append(stdout_path, stdout_file.read(4096))
                if stderr_file.channel.recv_stderr_ready():
                    _append(stderr_path, stderr_file.read(4096))
                time.sleep(0.05)
            _append(stdout_path, stdout_file.read())
            _append(stderr_path, stderr_file.read())
            code = int(stdout_file.channel.recv_exit_status())
        finally:
            on_complete(code)

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    return thread


def drain_channel(
    stdout_file: _ChannelReader,
    stderr_file: _ChannelReader,
) -> tuple[bytes, bytes, int]:
    out = stdout_file.read()
    err = stderr_file.read()
    code = int(stdout_file.channel.recv_exit_status())
    return out, err, code
