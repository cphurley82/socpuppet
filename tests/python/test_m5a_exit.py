"""M5a's exit test: the IO die's manager brings the link up, lets the
compute die go, and 🎭 the compute-side stand-in then reaches the IO die's
memory across the real link.

What the milestone map asks for is firmware doing this; M5a has 🎭 a script
in the manager's place (`sp.IoManager`), and M5b puts Zephyr there.
"""

import pytest

import socpuppet as sp
from socpuppet import ucie
from socpuppet.boards.io_manager import (
    HELLO,
    SCRATCH_BASE,
    io_manager,
    one_round_trip,
)
from socpuppet.boards.manager import stand_in_manager
from socpuppet.regs import ucie_link

#: Longer than bring-up takes, by enough that a failure is a failure.
LONG_ENOUGH = sp.ms(20)


def a_board(trace=False):
    """The board with 🎭 a compute die that does one round trip."""
    board = io_manager(
        compute=one_round_trip,
        manager=stand_in_manager().script,
        trace=trace,
    )
    board.platform.build()
    return board


def until_the_round_trip_has_landed(board):
    """Runs until the compute die's word is in the IO die's scratch."""
    return board.platform.run_until(
        lambda: (
            board.platform.peek32(SCRATCH_BASE, via=board.manager.cpu.socket)
            == HELLO
        ),
        timeout=LONG_ENOUGH,
    )


@pytest.mark.platform
class TestWhenTheManagerBoardRuns:
    def test_the_compute_die_round_trips_a_word_through_the_io_dies_memory(
        self,
    ):
        board = a_board()

        # 🎭 The round trip reads back what it wrote and says so if it
        # cannot, so landing at all is the round trip.
        assert until_the_round_trip_has_landed(board)

    def test_the_boot_goes_in_order_the_handshake_the_release_the_traffic(
        self,
    ):
        board = a_board(trace=True)
        assert until_the_round_trip_has_landed(board)

        said = ucie.sideband_packets(board.platform.trace)
        agreed = max(
            record.time
            for record, packet in said
            if (packet.msgcode, packet.msgsubcode)
            == ucie.MESSAGE_RDI_RSP_ACTIVE
        )
        released = next(
            record.time
            for record, packet in said
            if packet.opcode is ucie.Opcode.MEMORY_WRITE_32B
            and packet.address == ucie_link.DIE_RESET
        )
        crossed = min(
            record.time
            for record in board.platform.trace
            if record.source == board.link.a.peer_initiator.path
        )

        assert agreed < released < crossed
