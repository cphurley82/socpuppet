"""🎭 A stand-in for the IO die's management firmware: a script.

The IO die of a chiplet host is the one that brings the die-to-die link up
and lets the compute die out of reset. `IoManager` is that firmware as a
Python script, for a `ScriptedBusMaster` in the place of the IO die's CPU:

    manager = sp.IoManager(link=0x1001_0000)
    cpu = io.add("cpu", sp.ScriptedBusMaster(manager.script))

It is what the real firmware does, in the same order, so it is also the
place to read how a link is brought up:

1. Ask to be told when the link's status changes, and start training.
2. Sleep until the link says it is up.
3. Let the compute die go, by writing a zero to the reset register at the
   other end of the link, over the sideband.
4. Sleep. If the link goes down, train it again.

🎓 The registers it writes are UCIe's Link DVSEC
(`socpuppet.regs.ucie_link`). The link is up 4 ms after power-on at the
earliest, because UCIe holds it in reset that long, and training takes as
long again as the link was built to take.
"""

from __future__ import annotations

from socpuppet.ops import Steps, read32, wait, wait_irq, write32
from socpuppet.regs import ucie_link

#: How many times the manager looks at the mailbox before it gives up on
#: the other die. A sideband access takes no simulated time: what it waits
#: for is the two ends passing the packets between them.
_PATIENCE = 10


class IoManager:
    """🎭 Stand-in for the IO die's firmware, as a script for its CPU slot.

    `link` is where the link's register block is on the IO die's bus.
    `script` is the generator function to hand to a `ScriptedBusMaster`.

    ⚠️ It does nothing else: a real manager would also start the rest of
    the IO die, and would say something on a console about it.
    """

    def __init__(self, *, link: int) -> None:
        self._link = link

    def script(self) -> Steps[None]:
        """What the manager does, for ever: hand it to a ScriptedBusMaster."""
        yield from self._bring_the_link_up()
        yield from self._let_the_compute_die_go()
        while True:
            yield wait_irq()
            status = yield from self._acknowledged_status()
            if not status & ucie_link.STATUS_UP:
                # The link has gone down under us. Nothing crosses it
                # until it has been trained again.
                yield write32(
                    self._link + ucie_link.CONTROL, ucie_link.CONTROL_RETRAIN
                )
                yield from self._wait_until_the_link_is_up()

    def _bring_the_link_up(self) -> Steps[None]:
        yield write32(
            self._link + ucie_link.EVENT_NOTIFICATION,
            ucie_link.EVENT_NOTIFICATION_STATUS_CHANGED,
        )
        yield write32(
            self._link + ucie_link.CONTROL, ucie_link.CONTROL_START_TRAINING
        )
        yield from self._wait_until_the_link_is_up()

    def _wait_until_the_link_is_up(self) -> Steps[None]:
        while True:
            yield wait_irq()
            status = yield from self._acknowledged_status()
            if status & ucie_link.STATUS_UP:
                return

    def _acknowledged_status(self) -> Steps[int]:
        """The link's status, with what it says has happened cleared.

        The bit that says the status changed is cleared by writing a one
        to it, so that a change the firmware has not seen cannot be lost,
        and so that the link stops interrupting about this one.
        """
        status: int = yield read32(self._link + ucie_link.STATUS)
        if status & ucie_link.STATUS_CHANGED:
            yield write32(
                self._link + ucie_link.STATUS, ucie_link.STATUS_CHANGED
            )
        return status

    def _let_the_compute_die_go(self) -> Steps[None]:
        """Writes a zero to the reset register at the other end."""
        yield write32(
            self._link + ucie_link.MAILBOX_OPCODE,
            ucie_link.MAILBOX_OPCODE_CODE_MEMORY_WRITE_32B
            << ucie_link.MAILBOX_OPCODE_CODE_SHIFT,
        )
        yield write32(
            self._link + ucie_link.MAILBOX_ADDRESS, ucie_link.DIE_RESET
        )
        yield write32(self._link + ucie_link.MAILBOX_DATA, 0)
        yield write32(
            self._link + ucie_link.MAILBOX_TRIGGER,
            ucie_link.MAILBOX_TRIGGER_GO,
        )
        for _ in range(_PATIENCE):
            status = yield read32(self._link + ucie_link.MAILBOX_STATUS)
            if not status & ucie_link.MAILBOX_STATUS_BUSY:
                return
            yield wait(0)
        raise RuntimeError(
            "The other die never answered the write to its reset register. "
            "Is there an endpoint at the other end of the link, with its "
            "sideband peer ports bound to this one's?"
        )
