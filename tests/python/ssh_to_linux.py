"""🔌 This machine's ssh and scp, as the tests run them to Linux.

Linux is reached at a port of this machine's that a cable forwards to its
port 22 (`sp.EthernetCable`), as root, with no password.
"""

from pathlib import Path

#: How this machine's ssh and scp are told to reach Linux. No
#: configuration of this machine's own (-F /dev/null), no host key to
#: check or keep, since Linux's is made afresh at each boot, and no
#: question to wait on an answer to.
OPTIONS = (
    *("-F", "/dev/null"),
    *("-o", "StrictHostKeyChecking=no"),
    *("-o", "UserKnownHostsFile=/dev/null"),
    *("-o", "LogLevel=ERROR"),
    *("-o", "BatchMode=yes"),
)


def ssh(port: int, command: str) -> tuple[str, ...]:
    """The command line that runs `command` on Linux, at `port`."""
    return ("ssh", *OPTIONS, "-p", str(port), "root@localhost", command)


def scp(port: int, sent: Path, to: str) -> tuple[str, ...]:
    """The command line that sends `sent` to `to` on Linux, at `port`."""
    return ("scp", *OPTIONS, "-P", str(port), str(sent), f"root@localhost:{to}")
