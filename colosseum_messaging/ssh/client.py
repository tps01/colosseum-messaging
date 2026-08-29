from __future__ import annotations

from typing import TYPE_CHECKING

import paramiko
from colosseum.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping

_logger = get_logger("colosseum.messaging.ssh")


class SSHClientWrapper:
    def __init__(self, config: Mapping[str, object]) -> None:
        self._config = dict(config)
        self._client: paramiko.SSHClient | None = None
        driver = str(config.get("driver", "ssh")).lower()
        if driver == "sim":
            self._sim = True
            _logger.debug("SSH client sim mode enabled")
        else:
            self._sim = False
            self._connect_paramiko()

    def _connect_paramiko(self) -> None:
        auth = str(self._config.get("auth", "auto")).strip().lower()
        if auth in ("none", "auth_none"):
            self._connect_auth_none()
            return

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507  # bench DUT SSH
        connect_kwargs: dict[str, object] = {
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
        """Connect with Paramiko ``auth_none`` (passwordless DUT accounts)."""
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
        # Paramiko has no public setter; attach the authenticated transport.
        transport_attr = "_transport"
        setattr(client, transport_attr, transport)
        self._client = client
        _logger.debug("SSH connected to %s:%s as %s (auth=none)", hostname, port, username)

    def exec_stdout(self, command: str, timeout: float = 30.0) -> str:
        _logger.debug("SSH exec: %s (timeout=%ss)", command, timeout)
        if self._sim:
            response = self._sim_stdout(command)
        else:
            client = self._client
            if client is None:
                raise RuntimeError("SSH client is not connected")
            _stdin, stdout, _stderr = client.exec_command(  # nosec B601  # test script command
                command, timeout=timeout,
            )
            response = stdout.read().decode("utf-8", errors="replace").strip()
        preview = response[:200] + ("..." if len(response) > 200 else "")
        _logger.debug("SSH stdout: %r", preview)
        return response

    def _sim_stdout(self, command: str) -> str:
        cmd = command.strip()
        if "version" in cmd:
            return "v1.2.3"
        if "os-release" in cmd:
            return "present"
        return "ok"

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
