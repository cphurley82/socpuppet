"""🧦 The IO-die manager board: what is where, and what reaches what."""

import json

import pytest

from socpuppet.boards.io_manager import RAM_BASE, SCRATCH_BASE, io_manager


def nothing():
    """🎭 A compute die that does nothing at all."""
    yield from ()


class TestWhenTheBoardIsDescribed:
    def test_the_compute_dies_cpu_takes_its_reset_from_its_end_of_the_link(
        self,
    ):
        # What that reset does is tested where it can be seen: the compute
        # die reaches nothing until the manager lets it go
        # (test_io_manager.py, test_m5a_exit.py). This is that the line
        # comes from the link and from nowhere else.
        board = io_manager(compute=nothing)

        connections = json.loads(board.platform.to_json())["connections"]

        assert (
            board.link.a.reset.path,
            board.compute.reset.path,
        ) in [(one["source"], one["sink"]) for one in connections]


@pytest.mark.platform
class TestWhenTheBoardIsBuilt:
    def test_both_dies_reach_the_scratch_at_the_same_address(self):
        board = io_manager(compute=nothing)
        board.platform.build()

        board.platform.poke32(SCRATCH_BASE, 0x5EED, via=board.manager.socket)

        assert (
            board.platform.peek32(SCRATCH_BASE, via=board.compute.socket)
            == 0x5EED
        )

    def test_the_compute_dies_memory_is_its_own_and_not_the_other_dies(self):
        board = io_manager(compute=nothing)
        board.platform.build()

        board.platform.poke32(RAM_BASE, 0x5EED, via=board.compute.socket)

        # The window onto the IO die stops below the compute die's memory,
        # so the manager's bus has nothing at that address at all.
        with pytest.raises(LookupError):
            board.platform.peek32(RAM_BASE, via=board.manager.socket)
