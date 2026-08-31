from __future__ import annotations

from colosseum.decorators import command, measurement

from colosseum_messaging.connections import get_ssh_client
from colosseum_messaging.scp.client import ScpClientWrapper


def _scp(ssh_id: int) -> ScpClientWrapper:
    return ScpClientWrapper(get_ssh_client(ssh_id))


@command
def put(
    *,
    ssh_id: int,
    local: str,
    remote: str,
    key: str = "",
    recursive: bool = False,
    max_depth: int | None = None,
) -> None:
    """Upload local file(s) to the remote host via SCP."""
    _ = key
    _scp(ssh_id).put(local, remote, recursive=recursive, max_depth=max_depth)


@measurement
def get(
    *,
    ssh_id: int,
    remote: str,
    local: str,
    key: str,
    recursive: bool = False,
    max_depth: int | None = None,
    newest: int | None = None,
    oldest: int | None = None,
) -> list[str]:
    """Download remote file(s) via SCP."""
    _ = key
    return _scp(ssh_id).get(
        remote,
        local,
        recursive=recursive,
        max_depth=max_depth,
        newest=newest,
        oldest=oldest,
    )
