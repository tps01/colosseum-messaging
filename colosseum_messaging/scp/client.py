"""SCP transfers via cached SSH connections."""

from __future__ import annotations

from typing import TYPE_CHECKING

from colosseum_messaging._paths import resolve_artifact_path
from colosseum_messaging.ssh._file_select import map_remote_get_paths
from colosseum_messaging.ssh._remote_path import normalize_remote_path
from scp import SCPClient

if TYPE_CHECKING:
    from colosseum_messaging.ssh.client import SSHClientWrapper


class ScpClientWrapper:
    def __init__(self, ssh: SSHClientWrapper) -> None:
        self._ssh = ssh

    def get(
        self,
        remote: str,
        local: str,
        *,
        recursive: bool = False,
        max_depth: int | None = None,
        newest: int | None = None,
        oldest: int | None = None,
    ) -> list[str]:
        if self._ssh._sim:  # noqa: SLF001
            return self._ssh.sftp_get(
                remote,
                local,
                recursive=recursive,
                max_depth=max_depth,
                newest=newest,
                oldest=oldest,
            )

        remote_paths = self._ssh.resolve_remote_files(
            remote,
            recursive=recursive,
            max_depth=max_depth,
            newest=newest,
            oldest=oldest,
        )
        mappings = map_remote_get_paths(
            remote_paths,
            remote,
            local,
            resolve_local=resolve_artifact_path,
        )
        written: list[str] = []
        transport = self._ssh.get_transport()
        with SCPClient(transport) as scp:
            for remote_path, local_path in mappings:
                scp.get(remote_path, str(local_path))
                written.append(str(local_path))
        return written

    def put(
        self,
        local: str,
        remote: str,
        *,
        recursive: bool = False,
        max_depth: int | None = None,
    ) -> list[str]:
        if self._ssh._sim:  # noqa: SLF001
            return self._ssh.sftp_put(local, remote, recursive=recursive, max_depth=max_depth)

        from colosseum_messaging.ssh._file_select import map_local_put_paths, select_local_files

        selected = select_local_files(local, recursive=recursive, max_depth=max_depth)
        mappings = map_local_put_paths(
            [path for path, _mtime in selected],
            local,
            remote,
        )
        written: list[str] = []
        transport = self._ssh.get_transport()
        with SCPClient(transport) as scp:
            for local_path, remote_path in mappings:
                remote_normalized = normalize_remote_path(remote_path)
                if local_path.is_dir():
                    scp.put(str(local_path), remote_normalized, recursive=recursive)
                else:
                    scp.put(str(local_path), remote_normalized)
                written.append(remote_normalized)
        return written
