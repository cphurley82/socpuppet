"""What crossed the host's die-to-die link, read out of a trace.

For a host built with `trace=True` and a manager, so that the link is
the real one. The mainband carries what each die sends the other, and
the sideband the link's own management traffic.
"""

from socpuppet import ucie
from socpuppet.regs import ucie_link


def sent_to_the_io_die(board):
    """What the compute die sent across the link's mainband.

    ⚠️ An address here is the IO die's own: the compute die's bus has
    taken the start of its window off before the access crosses.
    """
    return [
        each
        for each in board.platform.trace
        if each.source == board.link.a.peer_initiator.path
    ]


def sent_to_the_compute_die(board):
    """What the IO die sent across the link's mainband.

    An address here is one of the compute die's, which is the host's.
    """
    return [
        each
        for each in board.platform.trace
        if each.source == board.link.b.peer_initiator.path
    ]


def when_the_host_was_let_go(board):
    """When the manager's write to the compute die's reset register crossed."""
    return min(
        record.time
        for record, packet in ucie.sideband_packets(board.platform.trace)
        if packet.opcode is ucie.Opcode.MEMORY_WRITE_32B
        and packet.address == ucie_link.DIE_RESET
        and not packet.data & ucie_link.DIE_RESET_ASSERTED
    )
