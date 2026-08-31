from __future__ import annotations

import contextlib
import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import paramiko
from colosseum.logging import get_logger

from colosseum_messaging._paths import resolve_artifact_path
from colosseum_messaging.ssh._background import (
    BackgroundJob,
    drain_channel,
    start_background_reader,
)
from colosseum_messaging.ssh._file_select import (
    map_local_put_paths,
    map_remote_get_paths,
    select_local_files,
    select_remote_files,
)
from colosseum_messaging.ssh._remote_path import normalize_remote_path, split_remote_path
from colosseum_messaging.ssh._sim import SimRemoteFS, seed_sim_fs, sim_exec_result

if TYPE_CHECKING:
    from collections.abc import Mapping

_logger = get_logger("colosseum.messaging.ssh")

ExecResult = dict[str, object]


class SSHClientWrapper:
    def __init__(self, config: Mapping[str, object]) -> None:
        self._config = dict(config)
        self._client: paramiko.SSHClient | None = None
        self._sftp: paramiko.SFTPClient | None = None
        self._sim_fs: SimRemoteFS | None = None
        self._platform: str | None = None
        self._jobs: dict[str, BackgroundJob] = {}
        self._jobs_lock = threading.Lock()
        driver = str(config.get("driver", "ssh")).lower()
        if driver == "sim":
            self._sim = True
            self._sim_fs = SimRemoteFS()
            seed_sim_fs(self._sim_fs, self._config)
            configured = str(config.get("platform", "")).strip().lower()
            self._platform = configured if configured in ("linux", "windows") else "linux"
            _logger.debug("SSH client sim mode enabled platform=%s", self._platform)
        else:
            self._sim = False
            self._sim_fs = None
            self._connect_paramiko()

    def _connect_paramiko(self) -> None:
        auth = str(self._config.get("auth", "auto")).strip().lower()
        if auth in ("none", "auth_none"):
            self._connect_auth_none()
            return

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507  # bench DUT SSH
        connect_kwargs: dict[str, Any] = {
            "hostname": str(self._config["host"]),
            "port": int(str(self._config.get("port", 22))),
            "username": str(self._config["username"]),
            "timeout": float(str(self._config.get("timeout", 30.0))),
        }
        password = self._config.get("password")
        key_filename = self._config.get("key_filename") or ""
        if key_filename:
            connect_kwargs["key_filename"] = str(key_filename)
        elif password is not None:
            connect_kwargs["password"] = str(password)
            connect_kwargs["allow_agent"] = False
            connect_kwargs["look_for_keys"] = False
        client.connect(**connect_kwargs)
        self._client = client
        _logger.debug(
            "SSH connected to %s:%s as %s",
            connect_kwargs["hostname"],
            connect_kwargs["port"],
            connect_kwargs["username"],
        )

    def _connect_auth_none(self) -> None:
        hostname = str(self._config["host"])
        port = int(str(self._config.get("port", 22)))
        username = str(self._config["username"])
        timeout = float(str(self._config.get("timeout", 30.0)))
        transport = paramiko.Transport((hostname, port))
        transport.banner_timeout = timeout
        transport.auth_timeout = timeout
        transport.start_client(timeout=timeout)
        transport.auth_none(username)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507  # bench DUT SSH
        transport_attr = "_transport"
        setattr(client, transport_attr, transport)
        self._client = client
        _logger.debug("SSH connected to %s:%s as %s (auth=none)", hostname, port, username)

    def get_platform(self) -> str:
        if self._platform is not None:
            return self._platform
        configured = str(self._config.get("platform", "")).strip().lower()
        if configured in ("linux", "windows"):
            self._platform = configured
            return self._platform
        if self._sim:
            self._platform = "linux"
            return self._platform
        result = self.exec("uname -s", timeout=5.0)
        stdout = str(result.get("stdout", ""))
        self._platform = "linux" if stdout.strip() else "windows"
        return self._platform

    def _case_sensitive_glob(self) -> bool:
        return self.get_platform() == "linux"

    def _require_client(self) -> paramiko.SSHClient:
        if self._client is None:
            raise RuntimeError("SSH client is not connected")
        return self._client

    def get_transport(self) -> paramiko.Transport:
        client = self._require_client()
        transport = client.get_transport()
        if transport is None:
            raise RuntimeError("SSH transport is not available")
        return transport

    def exec(
        self,
        command: str,
        *,
        timeout: float = 30.0,
        input_data: bytes | str | None = None,
        get_pty: bool = False,
        environment: Mapping[str, str] | None = None,
    ) -> ExecResult:
        _logger.debug("SSH exec: %s (timeout=%ss)", command, timeout)
        if self._sim:
            return sim_exec_result(command)

        client = self._require_client()
        stdin, stdout, stderr = client.exec_command(  # nosec B601  # test script command
            command,
            timeout=timeout,
            get_pty=get_pty,
            environment=dict(environment) if environment is not None else None,
        )
        if input_data is not None:
            payload = input_data.encode("utf-8") if isinstance(input_data, str) else input_data
            stdin.write(payload)
            stdin.flush()
        stdin.channel.shutdown_write()
        out_bytes, err_bytes, code = drain_channel(stdout, stderr)
        result: ExecResult = {
            "exit_code": code,
            "stdout": out_bytes.decode("utf-8", errors="replace"),
            "stderr": err_bytes.decode("utf-8", errors="replace"),
        }
        preview = str(result["stdout"])[:200]
        _logger.debug("SSH exit=%s stdout=%r", code, preview)
        return result

    def exec_stdout(self, command: str, timeout: float = 30.0) -> str:
        return str(self.exec(command, timeout=timeout)["stdout"]).strip()

    def exec_sequence(
        self,
        *,
        path: str | None = None,
        script: str | None = None,
        interpreter: str | None = None,
        timeout: float = 30.0,
    ) -> ExecResult:
        if (path is None) == (script is None):
            raise ValueError("Provide exactly one of path= or script=")

        if path is not None:
            local_path = Path(path)
            body = local_path.read_bytes()
            suffix = local_path.suffix.lower()
        else:
            body = (script or "").encode("utf-8")
            suffix = ""

        preview = body.decode("utf-8", errors="replace")[:200]
        if self._sim:
            return sim_exec_result("", script_preview=preview)

        delivery = self._sequence_delivery(suffix=suffix, interpreter=interpreter)
        if delivery["mode"] == "stdin":
            return self.exec(
                delivery["command"],
                timeout=timeout,
                input_data=body,
            )

        remote_name = f"colosseum-{uuid.uuid4().hex}"
        remote_path = normalize_remote_path(remote_name)
        sftp_client = self._require_sftp()
        try:
            with sftp_client.file(remote_path, "wb") as remote_file:
                remote_file.write(body)
            command = delivery["command"].format(remote=remote_path)
            result = self.exec(command, timeout=timeout)
        finally:
            with contextlib.suppress(OSError):
                sftp_client.remove(remote_path)
        return result

    def _sequence_delivery(
        self,
        *,
        suffix: str,
        interpreter: str | None,
    ) -> dict[str, str]:
        if interpreter is not None:
            if "{remote}" in interpreter:
                return {"mode": "upload", "command": interpreter}
            return {"mode": "stdin", "command": interpreter}

        platform = self.get_platform()
        if suffix in (".bat", ".cmd"):
            return {"mode": "upload", "command": "cmd /c {remote}"}
        if suffix == ".ps1":
            return {
                "mode": "upload",
                "command": "powershell -NoProfile -NonInteractive -File {remote}",
            }
        if suffix in (".sh", ".bash", ""):
            if platform == "windows" and suffix == "":
                return {
                    "mode": "stdin",
                    "command": "powershell -NoProfile -NonInteractive -Command -",
                }
            return {"mode": "stdin", "command": "bash -s"}
        if platform == "windows":
            return {"mode": "upload", "command": "cmd /c {remote}"}
        return {"mode": "stdin", "command": "bash -s"}

    def start(
        self,
        command: str,
        key: str,
        *,
        timeout: float = 30.0,
    ) -> tuple[str, str]:
        stdout_path = resolve_artifact_path(f"ssh_{key}.stdout.txt")
        stderr_path = resolve_artifact_path(f"ssh_{key}.stderr.txt")
        _logger.debug("SSH start: %s key=%s", command, key)

        if self._sim:
            stdout_path.write_text(self.exec_stdout(command, timeout=timeout), encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            job = BackgroundJob(
                key=key,
                command=command,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                thread=threading.Thread(),
                channel=None,
            )
            job.exit_code = 0
            job.done.set()
            with self._jobs_lock:
                self._jobs[key] = job
            return str(stdout_path), str(stderr_path)

        client = self._require_client()
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)  # nosec B601
        channel = stdout.channel

        def _on_complete(code: int) -> None:
            with self._jobs_lock:
                active = self._jobs.get(key)
                if active is not None:
                    active.exit_code = code
                    active.done.set()

        thread = start_background_reader(
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            stdout_file=stdout,
            stderr_file=stderr,
            on_complete=_on_complete,
        )
        job = BackgroundJob(
            key=key,
            command=command,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            thread=thread,
            channel=channel,
        )
        with self._jobs_lock:
            self._jobs[key] = job
        return str(stdout_path), str(stderr_path)

    def collect(self, key: str, *, timeout: float = 30.0) -> ExecResult:
        with self._jobs_lock:
            job = self._jobs.get(key)
        if job is None:
            raise KeyError(f"No background SSH job for key {key!r}")

        if not job.done.wait(timeout=timeout):
            if job.channel is not None:
                job.channel.close()
            job.done.set()

        stdout_text = (
            job.stdout_path.read_text(encoding="utf-8", errors="replace")
            if job.stdout_path.exists()
            else ""
        )
        stderr_text = (
            job.stderr_path.read_text(encoding="utf-8", errors="replace")
            if job.stderr_path.exists()
            else ""
        )
        code = 0 if job.exit_code is None else int(job.exit_code)
        return {"exit_code": code, "stdout": stdout_text, "stderr": stderr_text}

    def _require_sftp(self) -> paramiko.SFTPClient:
        if self._sftp is None:
            self._sftp = self._require_client().open_sftp()
        return self._sftp

    def _open_sftp(self) -> paramiko.SFTPClient | SimRemoteFS:
        if self._sim:
            if self._sim_fs is None:
                raise RuntimeError("Sim filesystem is not initialized")
            return self._sim_fs
        return self._require_sftp()

    def sftp_get(
        self,
        remote: str,
        local: str,
        *,
        recursive: bool = False,
        max_depth: int | None = None,
        newest: int | None = None,
        oldest: int | None = None,
    ) -> list[str]:
        sftp = self._open_sftp()
        selected = select_remote_files(
            sftp,
            remote,
            recursive=recursive,
            max_depth=max_depth,
            newest=newest,
            oldest=oldest,
            case_sensitive=self._case_sensitive_glob(),
        )
        mappings = map_remote_get_paths(
            [path for path, _mtime in selected],
            remote,
            local,
            resolve_local=resolve_artifact_path,
        )
        written: list[str] = []
        for remote_path, local_path in mappings:
            if self._sim:
                assert self._sim_fs is not None
                self._sim_fs.get_file(remote_path, local_path)
            else:
                self._require_sftp().get(remote_path, str(local_path))
            written.append(str(local_path))
        return written

    def sftp_put(
        self,
        local: str,
        remote: str,
        *,
        recursive: bool = False,
        max_depth: int | None = None,
    ) -> list[str]:
        selected = [(path, mtime) for path, mtime in select_local_files(
            local, recursive=recursive, max_depth=max_depth,
        )]
        mappings = map_local_put_paths(
            [path for path, _mtime in selected],
            local,
            remote,
        )
        written: list[str] = []
        for local_path, remote_path in mappings:
            if self._sim:
                assert self._sim_fs is not None
                self._sim_fs.put_file(remote_path, local_path)
            else:
                remote_parent = normalize_remote_path(remote_path).rsplit("/", 1)[0]
                sftp_client = self._require_sftp()
                try:
                    sftp_client.stat(remote_parent)
                except OSError:
                    self.sftp_mkdir(remote_parent)
                sftp_client.put(str(local_path), remote_path)
            written.append(remote_path)
        return written

    def sftp_listdir(self, path: str) -> list[str]:
        sftp = self._open_sftp()
        attrs = sftp.listdir_attr(normalize_remote_path(path))
        return [str(getattr(item, "filename", "")) for item in attrs]

    def sftp_mkdir(self, path: str) -> None:
        normalized = normalize_remote_path(path)
        if self._sim:
            assert self._sim_fs is not None
            self._sim_fs.mkdir(normalized)
            return
        sftp = self._require_sftp()
        drive, parts = split_remote_path(normalized)
        current = f"{drive}:" if drive else "/"
        if not parts:
            return
        for part in parts:
            current = normalize_remote_path(f"{current.rstrip('/')}/{part}")
            try:
                sftp.stat(current)
            except OSError:
                sftp.mkdir(current)

    def sftp_remove(self, path: str) -> None:
        normalized = normalize_remote_path(path)
        if self._sim:
            assert self._sim_fs is not None
            self._sim_fs.remove(normalized)
            return
        self._require_sftp().remove(normalized)

    def sftp_rename(self, old: str, new: str) -> None:
        old_norm = normalize_remote_path(old)
        new_norm = normalize_remote_path(new)
        if self._sim:
            assert self._sim_fs is not None
            self._sim_fs.rename(old_norm, new_norm)
            return
        self._require_sftp().rename(old_norm, new_norm)

    def resolve_remote_files(
        self,
        remote: str,
        *,
        recursive: bool = False,
        max_depth: int | None = None,
        newest: int | None = None,
        oldest: int | None = None,
    ) -> list[str]:
        sftp = self._open_sftp()
        selected = select_remote_files(
            sftp,
            remote,
            recursive=recursive,
            max_depth=max_depth,
            newest=newest,
            oldest=oldest,
            case_sensitive=self._case_sensitive_glob(),
        )
        return [path for path, _mtime in selected]

    def close(self) -> None:
        with self._jobs_lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if not job.done.is_set():
                if job.channel is not None:
                    job.channel.close()
                job.thread.join(timeout=1.0)
                job.done.set()
        if self._sftp is not None:
            self._sftp.close()
            self._sftp = None
        if self._client is not None:
            self._client.close()
            self._client = None
