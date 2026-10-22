"""SSH stream draining, background completion, and upload-and-execute."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest
from colosseum_messaging.ssh._background import drain_channel, start_background_reader
from colosseum_messaging.ssh.client import SSHClientWrapper

if TYPE_CHECKING:
    from pathlib import Path


class _Stream:
    def __init__(self, channel: object) -> None:
        self.channel = channel

    def read(self, size: int = -1) -> bytes:
        raise AssertionError("drain must use a bounded channel recv, not file read")


class _Pressure:
    """Stdout stays short until stderr is consumed; reading stdout to EOF would block."""

    def __init__(self) -> None:
        self._stdout = bytearray(b"short")
        self._stderr = bytearray(b"e" * 12000)

    def recv_ready(self) -> bool:
        return bool(self._stdout)

    def recv_stderr_ready(self) -> bool:
        return bool(self._stderr)

    def recv(self, nbytes: int) -> bytes:
        if not self._stdout:
            if self._stderr:
                raise AssertionError("stdout recv waited for EOF while stderr is buffered")
            return b""
        take = min(nbytes, len(self._stdout), 4096)
        chunk = bytes(self._stdout[:take])
        del self._stdout[:take]
        return chunk

    def recv_stderr(self, nbytes: int) -> bytes:
        take = min(nbytes, len(self._stderr), 4096)
        chunk = bytes(self._stderr[:take])
        del self._stderr[:take]
        return chunk

    def exit_status_ready(self) -> bool:
        return not self._stdout and not self._stderr

    def recv_exit_status(self) -> int:
        if not self.exit_status_ready():
            raise AssertionError("exit status read before both streams were drained")
        return 3


class _Interleaved:
    def __init__(self) -> None:
        self._events = [("out", b"A"), ("err", b"BB"), ("out", b"C")]

    def recv_ready(self) -> bool:
        return bool(self._events) and self._events[0][0] == "out"

    def recv_stderr_ready(self) -> bool:
        return bool(self._events) and self._events[0][0] == "err"

    def recv(self, nbytes: int) -> bytes:
        if not self.recv_ready():
            raise AssertionError("recv called while stdout is not the next stream")
        _kind, data = self._events.pop(0)
        return data[:nbytes]

    def recv_stderr(self, nbytes: int) -> bytes:
        if not self.recv_stderr_ready():
            raise AssertionError("recv_stderr called while stderr is not the next stream")
        _kind, data = self._events.pop(0)
        return data[:nbytes]

    def exit_status_ready(self) -> bool:
        return not self._events

    def recv_exit_status(self) -> int:
        return 0


class _SlowStdout:
    def __init__(self) -> None:
        self._chunk = b"hi"
        self.given = False
        self.exited = False

    def recv_ready(self) -> bool:
        return not self.given

    def recv(self, nbytes: int) -> bytes:
        if self.given:
            raise AssertionError("recv blocked for more stdout than is available")
        self.given = True
        return self._chunk[:nbytes]

    def recv_stderr_ready(self) -> bool:
        return False

    def recv_stderr(self, _nbytes: int) -> bytes:
        return b""

    def exit_status_ready(self) -> bool:
        return self.exited

    def recv_exit_status(self) -> int:
        return 0

    def gettimeout(self) -> None:
        return None


class _Silent:
    def __init__(self) -> None:
        self.closed = False

    def recv_ready(self) -> bool:
        return False

    def recv_stderr_ready(self) -> bool:
        return False

    def recv(self, _nbytes: int) -> bytes:
        raise AssertionError("recv blocked with nothing ready")

    def recv_stderr(self, _nbytes: int) -> bytes:
        raise AssertionError("recv_stderr blocked with nothing ready")

    def exit_status_ready(self) -> bool:
        return False

    def gettimeout(self) -> float:
        return 0.05


class _Finished:
    def __init__(self, code: int, stdout: bytes, jobs: dict[str, object], key: str) -> None:
        self.code = code
        self.stdout = stdout
        self._read = not stdout
        self.jobs = jobs
        self.key = key
        self.registered = False

    def recv_ready(self) -> bool:
        return not self._read

    def recv(self, nbytes: int) -> bytes:
        self._read = True
        return self.stdout[:nbytes]

    def recv_stderr_ready(self) -> bool:
        return False

    def recv_stderr(self, _nbytes: int) -> bytes:
        return b""

    def exit_status_ready(self) -> bool:
        return self._read

    def recv_exit_status(self) -> int:
        self.registered = self.key in self.jobs
        return self.code

    def close(self) -> None:
        return None


class _Hangs:
    def __init__(self) -> None:
        self.closed = False

    def recv_ready(self) -> bool:
        return False

    def recv_stderr_ready(self) -> bool:
        return False

    def recv(self, _nbytes: int) -> bytes:
        return b""

    def recv_stderr(self, _nbytes: int) -> bytes:
        return b""

    def exit_status_ready(self) -> bool:
        return self.closed

    def recv_exit_status(self) -> int:
        return 0

    def close(self) -> None:
        self.closed = True

    def gettimeout(self) -> None:
        return None


class _Broken:
    def recv_ready(self) -> bool:
        return True

    def recv(self, _nbytes: int) -> bytes:
        raise OSError("reader broke")

    def recv_stderr_ready(self) -> bool:
        return False

    def recv_stderr(self, _nbytes: int) -> bytes:
        return b""

    def exit_status_ready(self) -> bool:
        return False

    def close(self) -> None:
        return None


class _Exec:
    def __init__(self, channels: list[object]) -> None:
        self._channels = list(channels)

    def exec_command(
        self, _command: str, timeout: float | None = None, *, get_pty: bool = False,
    ):
        channel = self._channels.pop(0)
        return object(), _Stream(channel), _Stream(channel)


def _live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, channels: list[object],
) -> SSHClientWrapper:
    monkeypatch.setattr(
        "colosseum_messaging.ssh.client.resolve_artifact_path",
        lambda relative: tmp_path / relative,
    )
    client = SSHClientWrapper({"driver": "sim", "host": "sim.local", "username": "u"})
    client._sim = False
    client._client = _Exec(channels)  # type: ignore[assignment]
    return client


def test_drain_reads_large_stderr_before_stdout_eof() -> None:
    channel = _Pressure()
    stdout, stderr, code = drain_channel(_Stream(channel), _Stream(channel))
    assert stdout == b"short"
    assert stderr == b"e" * 12000
    assert code == 3


def test_drain_reads_interleaved_streams() -> None:
    channel = _Interleaved()
    stdout, stderr, code = drain_channel(_Stream(channel), _Stream(channel))
    assert stdout == b"AC"
    assert stderr == b"BB"
    assert code == 0


def test_background_reader_writes_short_chunk_before_exit(tmp_path: Path) -> None:
    channel = _SlowStdout()
    stdout_path = tmp_path / "out.txt"
    stderr_path = tmp_path / "err.txt"
    done = threading.Event()
    codes: list[int] = []

    def _on_complete(code: int) -> None:
        codes.append(code)
        done.set()

    def _on_error(exc: BaseException) -> None:
        raise AssertionError("reader failed") from exc

    thread = start_background_reader(
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        stdout_file=_Stream(channel),
        stderr_file=_Stream(channel),
        on_complete=_on_complete,
        on_error=_on_error,
    )
    thread.start()
    for _ in range(100):
        if stdout_path.exists() and stdout_path.read_bytes() == b"hi" and not channel.exited:
            break
        threading.Event().wait(0.01)
    else:
        raise AssertionError("short stdout chunk was not saved before the process exited")
    assert channel.exited is False
    channel.exited = True
    assert done.wait(2)
    assert codes == [0]
    thread.join(timeout=1)


def test_drain_times_out_when_no_status_arrives() -> None:
    channel = _Silent()
    with pytest.raises(TimeoutError, match="timed out"):
        drain_channel(_Stream(channel), _Stream(channel))


def test_immediate_completion_keeps_real_exit_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder: dict[str, object] = {}
    zero = _Finished(0, b"ok\n", holder, "zero")
    failed = _Finished(7, b"nope\n", holder, "failed")
    client = _live(tmp_path, monkeypatch, [zero, failed])
    zero.jobs = client._jobs
    failed.jobs = client._jobs
    client.start("true", "zero")
    client.start("false", "failed")
    assert client.collect("zero", timeout=2) == {
        "exit_code": 0,
        "stdout": "ok\n",
        "stderr": "",
    }
    assert client.collect("failed", timeout=2)["exit_code"] == 7
    assert zero.registered is True
    assert failed.registered is True


def test_collect_timeout_does_not_report_exit_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = _Hangs()
    client = _live(tmp_path, monkeypatch, [channel])
    client.start("sleep", "slow")
    with pytest.raises(TimeoutError, match="did not complete"):
        client.collect("slow", timeout=0)
    job = client._jobs["slow"]
    assert job.thread is not None
    job.thread.join(timeout=1)
    with pytest.raises(TimeoutError, match="did not complete"):
        client.collect("slow", timeout=0)
    assert job.exit_code != 0


def test_reader_failure_is_not_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _live(tmp_path, monkeypatch, [_Broken()])
    client.start("boom", "bad")
    with pytest.raises(RuntimeError, match="failed while reading"):
        client.collect("bad", timeout=2)


class _RemoteFile:
    def __init__(self, store: dict[str, object]) -> None:
        self._store = store

    def __enter__(self) -> _RemoteFile:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def write(self, payload: bytes) -> None:
        self._store["body"] = payload


class _SFTP:
    def __init__(self, directory: str, *, fail: bool = False) -> None:
        self.directory = directory
        self.fail = fail
        self.store: dict[str, object] = {}

    def normalize(self, path: str) -> str:
        if self.fail:
            raise OSError("normalize unavailable")
        assert path == "."
        return self.directory

    def file(self, path: str, mode: str) -> _RemoteFile:
        assert mode == "wb"
        self.store["path"] = path
        return _RemoteFile(self.store)

    def remove(self, path: str) -> None:
        self.store["removed"] = path


def _delivery_client(platform: str) -> SSHClientWrapper:
    client = SSHClientWrapper(
        {"driver": "sim", "host": "sim.local", "username": "u", "platform": platform},
    )
    client._sim = False
    return client


def test_windows_upload_keeps_ps1_suffix_and_quotes_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / "job.ps1"
    script.write_text("Write-Output ready\n", encoding="utf-8")
    sftp = _SFTP("C:/Users/tester/AppData/Local/Temp")
    commands: list[str] = []

    def _exec(
        command: str, timeout: float = 30.0, input_data: bytes | None = None,
    ) -> dict[str, object]:
        commands.append(command)
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    client = _delivery_client("windows")
    monkeypatch.setattr(client, "_require_sftp", lambda: sftp)
    monkeypatch.setattr(client, "exec", _exec)
    client.exec_sequence(path=str(script))
    remote = str(sftp.store["path"])
    assert remote.startswith("C:/Users/tester/AppData/Local/Temp/colosseum-")
    assert remote.endswith(".ps1")
    assert not remote.startswith("/colosseum-")
    assert sftp.store["removed"] == remote
    assert commands == [f'powershell -NoProfile -NonInteractive -File "{remote}"']


def test_upload_quotes_spaced_temp_dir_and_removes_the_same_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / "job.sh"
    script.write_text("echo hi\n", encoding="utf-8")
    sftp = _SFTP("/home/tester/My Files")

    def _exec(
        command: str, timeout: float = 30.0, input_data: bytes | None = None,
    ) -> dict[str, object]:
        raise RuntimeError(command)

    client = _delivery_client("linux")
    monkeypatch.setattr(client, "_require_sftp", lambda: sftp)
    monkeypatch.setattr(client, "exec", _exec)
    with pytest.raises(RuntimeError, match="bash "):
        client.exec_sequence(path=str(script), interpreter="bash {remote}")
    remote = str(sftp.store["path"])
    assert remote.startswith("/home/tester/My Files/colosseum-")
    assert remote.endswith(".sh")
    assert sftp.store["removed"] == remote


def test_upload_falls_back_to_tmp_when_home_cannot_be_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / "job.bat"
    script.write_text("echo hi\n", encoding="utf-8")
    sftp = _SFTP("/tmp", fail=True)
    commands: list[str] = []

    def _exec(
        command: str, timeout: float = 30.0, input_data: bytes | None = None,
    ) -> dict[str, object]:
        commands.append(command)
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    client = _delivery_client("linux")
    monkeypatch.setattr(client, "_require_sftp", lambda: sftp)
    monkeypatch.setattr(client, "exec", _exec)
    client.exec_sequence(path=str(script))
    remote = str(sftp.store["path"])
    assert remote.startswith("/tmp/colosseum-")
    assert remote.endswith(".bat")
    assert commands == [f"cmd /c '{remote}'"]
