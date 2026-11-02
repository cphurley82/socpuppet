"""🎭 The ports the tests choose, for a server on this machine to listen on."""

import pathlib
import socket
import subprocess
import sys

import pytest

import sockets
from sockets import a_free_port, free_ports

#: Enough tries that a choice left to chance would show.
TRIES = 20


@pytest.fixture
def only_two_ports(monkeypatch) -> list[int]:
    """All there is to choose from, so that a clash would show."""
    ports = free_ports(2)
    monkeypatch.setattr(sockets, "PORTS", ports)
    return ports


class TestWhenAPortIsChosen:
    def test_it_is_not_one_this_machine_hands_out_by_itself(self):
        first = first_port_handed_out()

        assert all(port < first for port in free_ports(TRIES))

    def test_one_something_is_bound_to_is_not_chosen(self, only_two_ports):
        spam, eggs = only_two_ports

        with socket.socket() as taken:
            taken.bind(("127.0.0.1", spam))

            assert [a_free_port() for _ in range(TRIES)] == [eggs] * TRIES


class TestWhenSeveralPortsAreChosen:
    def test_no_two_are_the_same(self, only_two_ports):
        for _ in range(TRIES):
            first, second = free_ports(2)

            assert first != second

    def test_more_than_there_are_is_refused_and_it_says_how_many(
        self, only_two_ports
    ):
        with pytest.raises(RuntimeError, match="3 free ports"):
            free_ports(3)


def first_port_handed_out() -> int:
    """Where this machine starts handing out ports by itself."""
    if sys.platform == "linux":
        ports = pathlib.Path("/proc/sys/net/ipv4/ip_local_port_range")
        return int(ports.read_text().split()[0])
    return int(
        subprocess.check_output(["sysctl", "-n", "net.inet.ip.portrange.first"])
    )
