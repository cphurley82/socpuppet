"""🧵 A run of the platform that keeps up with what is outside it.

`pump` runs a platform with far ends outside the simulation, such as this
machine's /dev/pciem, a socket or a terminal, each of which says it has
something by its file descriptor becoming readable:

    board = ssd(host=this_machine)
    board.platform.build()
    board.host.start()
    pump(board.platform, far_ends=[board.host], until=lambda: False)

💡 While the CPU works, the simulation runs as fast as it can. While it
sleeps, the simulated clock keeps to the wall's: a sleep of two seconds
takes two, and a far end that has something ends the wait. 🎓 QEMU does
the same with `-icount sleep=on`.
"""

import select
import time
from collections.abc import Callable, Sequence
from typing import Protocol

from socpuppet.platform import Platform
from socpuppet.time import s

#: Seconds on the wall between two looks at the far ends while the CPU
#: works: often enough that a key seems to land at once.
LOOK_EVERY = 0.01
#: The longest a sleeping CPU is waited for in one go, in seconds on the
#: wall. Firmware with nothing to do may set its timer days ahead.
LONGEST_WAIT = 1.0


class PumpedFarEnd(Protocol):
    """A far end of the platform's that a run keeps up with.

    It is outside the simulation: 🐧 this machine's /dev/pciem, a socket,
    or a terminal.
    """

    def fileno(self) -> int | None:
        """The descriptor to wait on, or None once there is none to.

        None once the descriptor would stay readable with nothing to read,
        such as input that has ended: the pump would never wait again.
        """
        ...

    def service(self) -> None:
        """Take what has arrived into the platform.

        The descriptor is readable. Before this returns, what arrived is
        scheduled in the platform (an event notified), so that the pump
        sees the platform has something to do, and the descriptor is no
        longer readable unless more has arrived.
        """
        ...

    def refresh(self) -> None:
        """Bring the outside up to date with the platform, at a look.

        Put out what the outside reads of the platform as it is now, and
        hand the platform anything that was held back until now.
        """
        ...


def pump(
    platform: Platform,
    *,
    far_ends: Sequence[PumpedFarEnd] = (),
    until: Callable[[], bool],
) -> None:
    """Run `platform`, keeping up with `far_ends`, until `until()`.

    Each far end whose descriptor is readable is serviced, and each is
    refreshed at each look, before `until` is asked. The far ends are
    looked at each time the CPU sleeps, and every `LOOK_EVERY` while it
    works. So the run may go a little past the moment `until` came true.

    🎓 A CPU that works is never more than a quantum ahead of the rest of
    the platform (`Platform.quantum`), so a next moment further off than
    that is a CPU asleep. That stretch is waited out on the wall, and a
    far end that has something ends the wait.
    """
    look_again = 0.0
    while True:
        ahead = platform.time_to_next_activity
        asleep = ahead is None or ahead > platform.quantum
        if not asleep and time.monotonic() < look_again:
            platform.step()
            continue
        for far_end in far_ends:
            far_end.refresh()
        if until():
            return
        if asleep:
            ready = _wait_out(platform, ahead, far_ends)
        else:
            ready = _readable(far_ends, 0)
            look_again = time.monotonic() + LOOK_EVERY
            platform.step()
        for far_end in ready:
            far_end.service()


def _wait_out(
    platform: Platform, ahead: int | None, far_ends: Sequence[PumpedFarEnd]
) -> list[PumpedFarEnd]:
    """Wait on the wall for a sleeping CPU's next moment, `ahead` of now.

    Or for `LONGEST_WAIT`, if that is sooner or nothing is ahead. A far end
    whose descriptor becomes readable ends the wait. The platform's clock
    moves on as far as the wall's did. Returns the far ends that are
    readable.
    """
    wait = LONGEST_WAIT if ahead is None else min(ahead / s(1), LONGEST_WAIT)
    waited_from = time.monotonic()
    ready = _readable(far_ends, wait)
    waited = s(time.monotonic() - waited_from)
    if ahead is not None and waited >= ahead:
        platform.step()
    elif waited:
        platform.run(waited)
    return ready


def _readable(
    far_ends: Sequence[PumpedFarEnd], seconds: float
) -> list[PumpedFarEnd]:
    """The far ends readable within `seconds`, or none if none are.

    With no descriptor to wait on, it is a plain wait.
    """
    waiting = {
        fd: each for each in far_ends if (fd := each.fileno()) is not None
    }
    if not waiting:
        time.sleep(seconds)
        return []
    ready, _, _ = select.select(list(waiting), [], [], seconds)
    return [waiting[fd] for fd in ready]
