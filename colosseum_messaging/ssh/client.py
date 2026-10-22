from __future__ import annotations

import contextlib
import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import paramiko
from colosseum.logging import get_logger

from colosseum_messaging._paths import resolve_artifact_path
from colosseum_messaging.exceptions import MessagingCapabilityError
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


class _HostKeyStore(Protocol):
    def lookup(self, hostname: str) -> object | None: ...

    def check(self, hostname: str, key: paramiko.PKey) -> bool: ...


def _store_trusts_key(
    store: _HostKeyStore, host_id: str, key: paramiko.PKey,
) -> bool | None:
    """Return True/False when ``host_id`` is present, or None when it is absent."""
    if store.lookup(host_id) is None:
        return None
    return bool(store.check(host_id, key))


def _quote_remote_path(path: str, *, windows: bool) -> str:
    if windows:
        return '"' + path.replace('"', '""') + '"'
    return "'" + path.replace("'", "'\"'\"'") + "'"


def _command_with_remote(template: str, remote_path: str, *, windows: bool) -> str:
    if '"{remote}"' in template or "'{remote}'" in template:
        return template.format(remote=remote_path)
    return template.format(remote=_quote_remote_path(remote_path, windows=windows))


ExecResult = dict[str, object]
_ALLOWED_DRIVERS = frozenset({"sim", "ssh"})
_ALLOWED_AUTH = frozenset({"", "auto", "none", "auth_none"})
_ALLOWED_PLATFORMS = frozenset({"", "linux", "windows"})


class SSHClientWrapper:
    def __init__(self, config: Mapping[str, object]) -> None:
        self._config = dict(config)
        self._client: paramiko.SSHClient | None = None
        self._sftp: paramiko.SFTPClient | None = None
        self._sim_fs: SimRemoteFS | None = None
        self._jobs: dict[str, BackgroundJob] = {}
        self._jobs_lock = threading.Lock()

        driver = str(config.get("driver", "ssh")).lower()
        if driver not in _ALLOWED_DRIVERS:
            raise ValueError(
                f"messaging.ssh driver must be one of {sorted(_ALLOWED_DRIVERS)}, got {driver!r}",
            )
        auth = str(config.get("auth", "auto")).strip().lower()
        if auth not in _ALLOWED_AUTH:
            raise ValueError(
                f"messaging.ssh auth must be one of "
                f"{sorted(a for a in _ALLOWED_AUTH if a)}, got {auth!r}",
            )
        configured = str(config.get("platform", "")).strip().lower()
        if configured not in _ALLOWED_PLATFORMS:
            raise ValueError(
                f"messaging.ssh platform must be 'linux' or 'windows', got {configured!r}",
            )
        self._platform = "linux" if configured == "" else configured

        if driver == "sim":
            self._sim = True
            self._sim_fs = SimRemoteFS()
            seed_sim_fs(self._sim_fs, self._config)
            _logger.debug("SSH client sim mode enabled platform=%s", self._platform)
        else:
            self._sim = False
            self._sim_fs = None
            self._connect_paramiko()

    @property
    def is_sim(self) -> bool:
        return self._sim

    def _load_host_keys(self, client: paramiko.SSHClient) -> None:
        known_hosts = self._config.get("known_hosts")
        if known_hosts:
            client.load_host_keys(str(known_hosts))
            return
        client.load_system_host_keys()

    def _apply_host_key_policy(self, client: paramiko.SSHClient) -> None:
        self._load_host_keys(client)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())

    def _require_known_host_key(self, hostname: str, port: int, key: paramiko.PKey) -> None:
        checker = paramiko.SSHClient()
        self._apply_host_key_policy(checker)
        host_id = hostname if port == 22 else f"[{hostname}]:{port}"
        # load_system_host_keys fills a separate store from get_host_keys().
        stores = (
            getattr(checker, "_system_host_keys", None),
            checker.get_host_keys(),
        )
        known = False
        for store in stores:
            if store is None:
                continue
            trusted = _store_trusts_key(store, host_id, key)
            if trusted is None:
                continue
            known = True
            if trusted:
                return
        if known:
            raise paramiko.SSHException(
                f"SSH host key for {host_id} does not match known_hosts",
            )
        raise paramiko.SSHException(f"SSH host key for {host_id} is not in known_hosts")

    def _require_sim_fs(self) -> SimRemoteFS:
        sim_fs = self._sim_fs
        if sim_fs is None:
            raise RuntimeError("SSH sim filesystem is not initialized")
        return sim_fs

    def _connect_paramiko(self) -> None:
        auth = str(self._config.get("auth", "auto")).strip().lower()
        if auth in ("none", "auth_none"):
            self._connect_auth_none()
            return

        client = paramiko.SSHClient()
        self._apply_host_key_policy(client)
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
        try:
            remote_key = transport.get_remote_server_key()
            self._require_known_host_key(hostname, port, remote_key)
        except (OSError, paramiko.SSHException):
            transport.close()
            raise
        transport.auth_none(username)
        client = paramiko.SSHClient()
        self._apply_host_key_policy(client)
        transport_attr = "_transport"
        setattr(client, transport_attr, transport)
        self._client = client
        _logger.debug("SSH connected to %s:%s as %s (auth=none)", hostname, port, username)

    def get_platform(self) -> str:
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
    ) -> ExecResult:
        _logger.debug("SSH exec: %s (timeout=%ss)", command, timeout)
        if self._sim:
            return sim_exec_result(command)

        client = self._require_client()
        stdin, stdout, stderr = client.exec_command(  # nosec B601  # test script command
            command,
            timeout=timeout,
            get_pty=get_pty,
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

        sftp_client = self._require_sftp()
        remote_path = self._sequence_remote_path(sftp_client, suffix)
        try:
            with sftp_client.file(remote_path, "wb") as remote_file:
                remote_file.write(body)
            command = _command_with_remote(
                delivery["command"],
                remote_path,
                windows=self.get_platform() == "windows",
            )
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
        if suffix in (".sh", ".bash"):
            return {"mode": "stdin", "command": "bash -s"}
        if suffix == "":
            if platform == "windows":
                raise MessagingCapabilityError(
                    "exec_sequence on Windows requires interpreter= "
                    "(Linux-first SSH; see README)",
                )
            return {"mode": "stdin", "command": "bash -s"}
        if platform == "windows":
            raise MessagingCapabilityError(
                f"exec_sequence suffix {suffix!r} on Windows requires interpreter= "
                "(Linux-first SSH; see README)",
            )
        return {"mode": "stdin", "command": "bash -s"}

    def _sequence_remote_path(self, sftp: paramiko.SFTPClient, suffix: str) -> str:
        directory = self._writable_remote_directory(sftp)
        name = f"colosseum-{uuid.uuid4().hex}{suffix}"
        return normalize_remote_path(f"{directory}/{name}")

    def _writable_remote_directory(self, sftp: paramiko.SFTPClient) -> str:
        normalize = getattr(sftp, "normalize", None)
        current: object = None
        if callable(normalize):
            try:
                current = normalize(".")
            except OSError:
                current = None
        if current:
            return str(current).rstrip("/\\")
        if self.get_platform() == "windows":
            return "C:/Users/Public"
        return "/tmp"

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
                thread=None,
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
        job = BackgroundJob(
            key=key,
            command=command,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            thread=None,
            channel=channel,
        )

        def _on_complete(code: int) -> None:
            if job.abandoned:
                return
            job.exit_code = code
            job.done.set()

        def _on_error(exc: BaseException) -> None:
            if job.abandoned:
                return
            job.error = exc
            job.done.set()

        thread = start_background_reader(
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            stdout_file=stdout,
            stderr_file=stderr,
            on_complete=_on_complete,
            on_error=_on_error,
        )
        job.thread = thread
        with self._jobs_lock:
            self._jobs[key] = job
        thread.start()
        return str(stdout_path), str(stderr_path)

    def collect(self, key: str, *, timeout: float = 30.0) -> ExecResult:
        with self._jobs_lock:
            job = self._jobs.get(key)
        if job is None:
            raise KeyError(f"No background SSH job for key {key!r}")

        if job.abandoned or (
            not job.done.wait(timeout=timeout) and not job.done.is_set()
        ):
            job.abandoned = True
            if job.channel is not None:
                job.channel.close()
            raise TimeoutError(f"SSH job {key!r} did not complete within {timeout}s")
        if job.error is not None:
            raise RuntimeError(f"SSH job {key!r} failed while reading output") from job.error
        if job.exit_code is None:
            job.abandoned = True
            raise TimeoutError(f"SSH job {key!r} did not complete within {timeout}s")

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
        return {
            "exit_code": int(job.exit_code),
            "stdout": stdout_text,
            "stderr": stderr_text,
        }

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
                self._require_sim_fs().get_file(remote_path, local_path)
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
                self._require_sim_fs().put_file(remote_path, local_path)
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
            self._require_sim_fs().mkdir(normalized)
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
            self._require_sim_fs().remove(normalized)
            return
        self._require_sftp().remove(normalized)

    def sftp_rename(self, old: str, new: str) -> None:
        old_norm = normalize_remote_path(old)
        new_norm = normalize_remote_path(new)
        if self._sim:
            self._require_sim_fs().rename(old_norm, new_norm)
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
                if job.thread is not None:
                    job.thread.join(timeout=1.0)
                job.done.set()
        if self._sftp is not None:
            self._sftp.close()
            self._sftp = None
        if self._client is not None:
            self._client.close()
            self._client = None
