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
_SSH_STDOUT_COMMANDS = (
    *_SSH_EXEC_COMMANDS,
    "ssh.measure_stdout",
)


@measurement
def exec(  # noqa: A001
    *,
    ssh_id: int,
    command: str,
    key: str,
    timeout: float = 30.0,
    retries: int = 3,
    input: bytes | str | None = None,  # noqa: A002
    get_pty: bool = False,
) -> dict[str, object]:
    """Run a remote command and record exit code plus stdout/stderr.

    :param timeout: Command timeout. A number is seconds; a string may use
        duration suffixes (``61s``, ``500ms``, ``1m``).
    :param retries: Total connection attempts (default 3); 0 disables retries.
        Applies only when opening a connection, never to command execution.

    :param ssh_id: Integer ID from the configured messaging.ssh row. Select an existing ID in
        that section.
    :param command: Remote shell command to execute; syntax follows the configured remote
        platform.
    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide.
    :param input: Optional input bytes or text sent to the remote command's stdin.
    :param get_pty: Request a remote pseudo-terminal when true; defaults to false.

    :returns: Dictionary with exit_code, stdout, and stderr. A nonzero exit code requires an
        explicit verify_exit check.
    """
    _ = key
    return get_ssh_client(ssh_id, retries=retries).exec(
        command,
        timeout=timeout,
        input_data=input,
        get_pty=get_pty,
    )


@measurement
def measure_stdout(
    *, ssh_id: int, command: str, key: str, timeout: float = 30.0, retries: int = 3,
) -> str:
    """Run a remote command and record stdout (stripped).

    :param retries: Total connection attempts (default 3); 0 disables retries.
        Cached connections are reused; operations are never replayed.

    :param ssh_id: Integer ID from the configured messaging.ssh row. Select an existing ID in
        that section.
    :param command: Remote shell command to execute; syntax follows the configured remote
        platform.
    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide.
    :param timeout: Command execution or collection timeout in seconds, independent of the
        connection timeout in TOML. Default: ``30.0``.

    :returns: Stripped remote stdout text, recorded as measurement evidence.
    """
    _ = key
    return get_ssh_client(ssh_id, retries=retries).exec_stdout(command, timeout=timeout)


@measurement
def exec_sequence(
    *,
    ssh_id: int,
    key: str,
    path: str | None = None,
    script: str | None = None,
    interpreter: str | None = None,
    timeout: float = 30.0,
    retries: int = 3,
) -> dict[str, object]:
    """Run a local script file or inline script as one remote process.

    :param retries: Total connection attempts (default 3); 0 disables retries.
        Cached connections are reused; operations are never replayed.

    :param ssh_id: Integer ID from the configured messaging.ssh row. Select an existing ID in
        that section.
    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide.
    :param path: Local script file, mutually exclusive with script; relative paths use the
        working directory.
    :param script: Inline script text, mutually exclusive with path.
    :param interpreter: Explicit remote interpreter. A {remote} placeholder selects upload-and-
        execute; otherwise script text is sent over stdin.
    :param timeout: Command execution or collection timeout in seconds, independent of the
        connection timeout in TOML. Default: ``30.0``.

    :returns: Dictionary with exit_code, stdout, and stderr. A nonzero exit code requires an
        explicit verify_exit check.
    """
    _ = key
    return get_ssh_client(ssh_id, retries=retries).exec_sequence(
        path=path,
        script=script,
        interpreter=interpreter,
        timeout=timeout,
    )


@command
def start(
    *, ssh_id: int, command: str, key: str, timeout: float = 30.0, retries: int = 3,
) -> None:
    """Start a remote command in the background; stdout/stderr stream to run artifacts.

    :param retries: Total connection attempts (default 3); 0 disables retries.
        Cached connections are reused; operations are never replayed.

    :param ssh_id: Integer ID from the configured messaging.ssh row. Select an existing ID in
        that section.
    :param command: Remote shell command to execute; syntax follows the configured remote
        platform.
    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide.
    :param timeout: Command execution or collection timeout in seconds, independent of the
        connection timeout in TOML. Default: ``30.0``.

    :returns: None; the command outcome is recorded.


    Pair with collect using the same ssh_id and key, then verify_exit.
    See the SSH workflow guide for timeouts and output-file lifetime.
    """
    _ = key
    get_ssh_client(ssh_id, retries=retries).start(command, key, timeout=timeout)


@measurement
def collect(
    *, ssh_id: int, key: str, timeout: float = 30.0, retries: int = 3,
) -> dict[str, object]:
    """Wait for a background command and record exit code plus stdout/stderr.

    :param retries: Total connection attempts (default 3); 0 disables retries.
        Cached connections are reused; operations are never replayed.

    :param ssh_id: Integer ID from the configured messaging.ssh row. Select an existing ID in
        that section.
    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide.
    :param timeout: Command execution or collection timeout in seconds, independent of the
        connection timeout in TOML. Default: ``30.0``.

    :returns: Dictionary with exit_code, stdout, and stderr. A nonzero exit code requires an
        explicit verify_exit check.
    """
    _ = key
    return get_ssh_client(ssh_id, retries=retries).collect(key, timeout=timeout)


@command
def put(
    *,
    ssh_id: int,
    local: str,
    remote: str,
    key: str = "",
    recursive: bool = False,
    max_depth: int | None = None,
    retries: int = 3,
) -> None:
    """Upload local file(s) to the remote host via SFTP.

    :param retries: Total connection attempts (default 3); 0 disables retries.
        Cached connections are reused; operations are never replayed.

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
    get_ssh_client(ssh_id, retries=retries).sftp_put(
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
    retries: int = 3,
    newest: int | None = None,
    oldest: int | None = None,
) -> list[str]:
    """Download remote file(s) via SFTP.

    :param retries: Total connection attempts (default 3); 0 disables retries.
        Cached connections are reused; operations are never replayed.

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
    return get_ssh_client(ssh_id, retries=retries).sftp_get(
        remote,
        local,
        recursive=recursive,
        max_depth=max_depth,
        newest=newest,
        oldest=oldest,
    )


@measurement
def listdir(*, ssh_id: int, path: str, key: str, retries: int = 3) -> list[str]:
    """List a remote directory via SFTP.

    :param retries: Total connection attempts (default 3); 0 disables retries.
        Cached connections are reused; operations are never replayed.

    :param ssh_id: Integer ID from the configured messaging.ssh row. Select an existing ID in
        that section.
    :param path: Remote file or directory path, interpreted for the configured remote platform.
    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide.

    :returns: Returned value described above, recorded as evidence for decorated measurements.
    """
    _ = key
    return get_ssh_client(ssh_id, retries=retries).sftp_listdir(path)


@command
def mkdir(*, ssh_id: int, path: str, key: str = "", retries: int = 3) -> None:
    """Create a remote directory via SFTP.

    :param retries: Total connection attempts (default 3); 0 disables retries.
        Cached connections are reused; operations are never replayed.

    :param ssh_id: Integer ID from the configured messaging.ssh row. Select an existing ID in
        that section.
    :param path: Remote file or directory path, interpreted for the configured remote platform.
    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide. Default: ``''``.

    :returns: None; the command outcome is recorded.
    """
    _ = key
    get_ssh_client(ssh_id, retries=retries).sftp_mkdir(path)


@command
def remove(*, ssh_id: int, path: str, key: str = "", retries: int = 3) -> None:
    """Remove a remote file via SFTP.

    :param retries: Total connection attempts (default 3); 0 disables retries.
        Cached connections are reused; operations are never replayed.

    :param ssh_id: Integer ID from the configured messaging.ssh row. Select an existing ID in
        that section.
    :param path: Remote file or directory path, interpreted for the configured remote platform.
    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide. Default: ``''``.

    :returns: None; the command outcome is recorded.
    """
    _ = key
    get_ssh_client(ssh_id, retries=retries).sftp_remove(path)


@command
def rename(
    *, ssh_id: int, old: str, new: str, key: str = "", retries: int = 3,
) -> None:
    """Rename a remote path via SFTP.

    :param retries: Total connection attempts (default 3); 0 disables retries.
        Cached connections are reused; operations are never replayed.

    :param ssh_id: Integer ID from the configured messaging.ssh row. Select an existing ID in
        that section.
    :param old: Existing remote path to rename.
    :param new: Destination remote path for the rename.
    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide. Default: ``''``.

    :returns: None; the command outcome is recorded.
    """
    _ = key
    get_ssh_client(ssh_id, retries=retries).sftp_rename(old, new)


def _lookup_ssh_measurement(
    key: str, commands: tuple[str, ...],
) -> tuple[object | None, str | None]:
    """Return ``(value, error)`` for a unique SSH measurement key among ``commands``."""
    ctx = get_context()
    hits: list[object] = []
    for command_name in commands:
        row = ctx.db.get_measurement("messaging", command_name, key, row_index=0)
        if row is not None and row.value is not None:
            hits.append(cast("object", row.value))
    if not hits:
        return None, None
    if len(hits) > 1:
        return None, (
            f"ambiguous SSH measurement key {key!r}: "
            "matches multiple commands; use a distinct key per call"
        )
    return hits[0], None


@verification
def verify_exit(*, key: str, expected: int = 0, optional: bool = False) -> VerificationResult:
    """Verify a prior SSH exec measurement has the expected exit code.

    The ``key`` must match exactly one prior exec/sequence/collect measurement.

    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide.
    :param expected: Expected remote exit code; zero normally denotes success. Default: ``0``.
    :param optional: When true, retain an unsuccessful outcome without failing the aggregate
        result. Commands and measurements also suppress their operation exception; a failed
        measurement returns None. Defaults to false.

    :returns: Recorded verification outcome (PASS, FAIL, ERROR, or BLOCKED), including the
        actual value when available.
    """
    value, ambiguity = _lookup_ssh_measurement(key, _SSH_EXEC_COMMANDS)
    if ambiguity is not None:
        return VerificationResult(status="ERROR", message=ambiguity, optional=optional)
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
    """Verify prior SSH stdout (exec dict or ``measure_stdout`` string) matches a regex.

    :param key: Evidence key for this operation. Keep distinct keys for separate facts; see the
        evidence lookup rules in the core guide.
    :param pattern: Regular expression searched in the recorded text; invalid expressions
        produce an error.
    :param optional: When true, retain an unsuccessful outcome without failing the aggregate
        result. Commands and measurements also suppress their operation exception; a failed
        measurement returns None. Defaults to false.

    :returns: Recorded verification outcome (PASS, FAIL, ERROR, or BLOCKED), including the
        actual value when available.
    """
    value, ambiguity = _lookup_ssh_measurement(key, _SSH_STDOUT_COMMANDS)
    if ambiguity is not None:
        return VerificationResult(status="ERROR", message=ambiguity, optional=optional)
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
