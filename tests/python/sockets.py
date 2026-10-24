"""Sockets of this machine's, for the tests that reach it over the cable."""

import socket


def a_free_port() -> int:
    """A TCP port of this machine's that nothing listens on, just now."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
