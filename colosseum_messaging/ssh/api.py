from __future__ import annotations

import re
from typing import cast

from colosseum.context import get_context
from colosseum.decorators import (
    VerificationResult,
    command,
    measurement,
    missing_measurement_result,
    verification,
)

from colosseum_messaging.connections import get_ssh_client

_SSH_EXEC_COMMANDS = (
    "ssh.exec",
    "ssh.exec_sequence",
    "ssh.collect",
)


@measurement
def exec(  # noqa: A001
    *,
    ssh_id: int,
    command: str,
    key: str,
    timeout: float = 30.0,
    input: bytes | str | None = None,  # noqa: A002
    get_pty: bool = False,
) -> dict[str, object]:
    """Run a remote command and record exit code plus stdout/stderr."""
    _ = key
    return get_ssh_client(ssh_id).exec(
        command,
        timeout=timeout,
        input_data=input,
        get_pty=get_pty,
    )


@measurement
def measure_stdout(*, ssh_id: int, command: str, key: str, timeout: float = 30.0) -> str:
    """Run a remote command and record stdout (stripped)."""
    _ = key
    return get_ssh_client(ssh_id).exec_stdout(command, timeout=timeout)


@measurement
def exec_sequence(
    *,
    ssh_id: int,
    key: str,
    path: str | None = None,
    script: str | None = None,
    interpreter: str | None = None,
    timeout: float = 30.0,
) -> dict[str, object]:
    """Run a local script file or inline script as one remote process."""
    _ = key
    return get_ssh_client(ssh_id).exec_sequence(
        path=path,
        script=script,
        interpreter=interpreter,
        timeout=timeout,
    )


@command
def start(*, ssh_id: int, command: str, key: str, timeout: float = 30.0) -> None:
    """Start a remote command in the background; stdout/stderr stream to run artifacts."""
    _ = key
    get_ssh_client(ssh_id).start(command, key, timeout=timeout)


@measurement
def collect(*, ssh_id: int, key: str, timeout: float = 30.0) -> dict[str, object]:
    """Wait for a background command and record exit code plus stdout/stderr."""
    _ = key
    return get_ssh_client(ssh_id).collect(key, timeout=timeout)


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
    """Upload local file(s) to the remote host via SFTP."""
    _ = key
    get_ssh_client(ssh_id).sftp_put(
        local, remote, recursive=recursive, max_depth=max_depth,
    )


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
    """Download remote file(s) via SFTP."""
    _ = key
    return get_ssh_client(ssh_id).sftp_get(
        remote,
        local,
        recursive=recursive,
        max_depth=max_depth,
        newest=newest,
        oldest=oldest,
    )


@measurement
def listdir(*, ssh_id: int, path: str, key: str) -> list[str]:
    """List a remote directory via SFTP."""
    _ = key
    return get_ssh_client(ssh_id).sftp_listdir(path)


@command
def mkdir(*, ssh_id: int, path: str, key: str = "") -> None:
    """Create a remote directory via SFTP."""
    _ = key
    get_ssh_client(ssh_id).sftp_mkdir(path)


@command
def remove(*, ssh_id: int, path: str, key: str = "") -> None:
    """Remove a remote file via SFTP."""
    _ = key
    get_ssh_client(ssh_id).sftp_remove(path)


@command
def rename(*, ssh_id: int, old: str, new: str, key: str = "") -> None:
    """Rename a remote path via SFTP."""
    _ = key
    get_ssh_client(ssh_id).sftp_rename(old, new)


def _lookup_ssh_exec(key: str) -> object | None:
    ctx = get_context()
    for command_name in _SSH_EXEC_COMMANDS:
        row = ctx.db.get_measurement("messaging", command_name, key, row_index=0)
        if row is not None and row.value is not None:
            return cast("object", row.value)
    return None


@verification
def verify_exit(*, key: str, expected: int = 0, optional: bool = False) -> VerificationResult:
    """Verify a prior SSH exec measurement has the expected exit code."""
    value = _lookup_ssh_exec(key)
    if value is None:
        return missing_measurement_result(key=key, optional=optional)
    if not isinstance(value, dict) or "exit_code" not in value:
        return VerificationResult(
            status="ERROR",
            message=f"SSH measurement {key!r} is not an exec result dict",
            optional=optional,
            actual=value,
        )
    actual = int(value["exit_code"])
    if actual == int(expected):
        return VerificationResult(status="PASS", message="", optional=optional, actual=actual)
    return VerificationResult(
        status="FAIL",
        message=f"expected exit {expected}, got {actual}",
        optional=optional,
        actual=actual,
    )


@verification
def verify_stdout_match(
    *,
    key: str,
    pattern: str,
    optional: bool = False,
) -> VerificationResult:
    """Verify a prior SSH exec measurement stdout matches a regex."""
    value = _lookup_ssh_exec(key)
    if value is None:
        return missing_measurement_result(key=key, optional=optional)
    stdout = str(value["stdout"]) if isinstance(value, dict) and "stdout" in value else str(value)
    if re.search(pattern, stdout):
        return VerificationResult(status="PASS", message="", optional=optional, actual=stdout)
    return VerificationResult(
        status="FAIL",
        message=f"pattern {pattern!r} not found in {stdout!r}",
        optional=optional,
        actual=stdout,
    )
