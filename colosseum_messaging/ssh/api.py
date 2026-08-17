from __future__ import annotations

from colosseum.decorators import measurement

from colosseum_messaging.connections import get_ssh_client


@measurement
def measure_stdout(*, ssh_id: int, command: str, key: str, timeout: float = 30.0) -> str:
    """Run a remote command and record stdout.

    :param ssh_id: Configured ``messaging.ssh`` id from bench TOML.
    :type ssh_id: int
    :param command: Shell command executed on the remote host.
    :type command: str
    :param key: Unique measurement key within domain ``messaging``.
    :type key: str
    :param timeout: Remote command timeout in seconds.
    :type timeout: float, optional

    :returns: Standard output text (stripped by the SSH client).
    :rtype: str

    :raises RuntimeError: On SSH connection or command failure.
    """
    _ = key
    return get_ssh_client(ssh_id).exec_stdout(command, timeout=timeout)
