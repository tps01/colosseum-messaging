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
    """Upload local file(s) to the remote host via SCP.

    :param ssh_id: Integer ID from the configured messaging.ssh row. Select an existing ID in
        that section.
    :param local: Existing local source file/path pattern; resolved from the working directory.
    :param remote: Remote source path/glob for get, or destination path for put; follows the
        configured remote platform.
    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide. Default: ``''``.
    :param recursive: Include directory descendants when true; defaults to false.
    :param max_depth: Maximum recursive descent depth; None leaves depth unbounded.

    :returns: None; the command outcome is recorded.
    """
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
    """Download remote file(s) via SCP.

    :param ssh_id: Integer ID from the configured messaging.ssh row. Select an existing ID in
        that section.
    :param remote: Remote source path/glob for get, or destination path for put; follows the
        configured remote platform.
    :param local: Local download destination under the active run output directory unless
        absolute; requires artifacts enabled.
    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide.
    :param recursive: Include directory descendants when true; defaults to false.
    :param max_depth: Maximum recursive descent depth; None leaves depth unbounded.
    :param newest: Select this many newest matching files by modification time; None disables
        selection. Mutually exclusive with oldest.
    :param oldest: Select this many oldest matching files by modification time; None disables
        selection. Mutually exclusive with newest.

    :returns: List of saved local download paths, recorded as measurement evidence.
    """
    _ = key
    return _scp(ssh_id).get(
        remote,
        local,
        recursive=recursive,
        max_depth=max_depth,
        newest=newest,
        oldest=oldest,
    )
