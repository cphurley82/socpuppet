"""Ports of this machine's, for the tests' servers to listen on."""

import contextlib
import errno
import secrets
import socket

#: The ports chosen from. 💡 All below the ones the machine hands out by itself
#: (Linux from 32768, macOS from 49152), to whatever connects anywhere. A port
#: is let go before its server binds it, and one of those could be handed to
#: another test in that moment, which `bind` then calls already in use.
PORTS = range(10_000, 32_768)


def a_free_port() -> int:
    """A TCP port of this machine's that nothing is bound to, just now."""
    (port,) = free_ports(1)
    return port


def free_ports(count: int) -> list[int]:
    """`count` TCP ports nothing is bound to, no two the same.

    Each is held until all are found, so that none is chosen twice.
    """
    with contextlib.ExitStack() as held:
        ports: list[int] = []
        for port in secrets.SystemRandom().sample(PORTS, k=len(PORTS)):
            probe = held.enter_context(socket.socket())
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            ports.append(port)
            if len(ports) == count:
                return ports
    raise RuntimeError(f"There are not {count} free ports among {PORTS}.")


def listening(port: int) -> bool:
    """Whether something on this machine is listening on `port`."""
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as error:
            if error.errno == errno.EADDRINUSE:
                return True
            raise
    return False
