"""Several consoles, heard as one story."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import NamedTuple

from socpuppet.placed import PlacedUart
from socpuppet.platform import Platform


class Line(NamedTuple):
    """One line that a console printed."""

    #: The simulated time when the transcript found the line whole, in the
    #: unit `ns` and `us` return.
    time: int
    #: Whose console it was, by the name the transcript was given for it.
    who: str
    #: What it said, without the end of the line.
    text: str


class Transcript:
    """What several consoles say during a run, as one story.

    A transcript hears nothing by itself: `listen()` notes what is new.
    Its own `run_until` runs the platform and listens as the run goes on.

    Lines heard by different listens are in the order they were said.
    ⚠️ Lines from two consoles heard by the same `listen` have the same
    time and are in the order the consoles were given, because nothing
    says which came first. With a CPU behind each console that is
    anything said within a quantum, the time one CPU may run ahead of
    another.
    """

    def __init__(
        self, platform: Platform, consoles: Mapping[str, PlacedUart]
    ) -> None:
        self.lines: list[Line] = []
        self._platform = platform
        self._consoles = consoles
        # How much of each console's output has been noted.
        self._heard = dict.fromkeys(consoles, 0)

    def listen(self) -> None:
        """Note the lines each console has printed since the last time."""
        for who, console in self._consoles.items():
            output = console.output
            # A line that has not ended yet is left for the next time.
            whole = output.rfind("\n") + 1
            self.lines += [
                Line(self._platform.time, who, text)
                for text in output[self._heard[who] : whole].splitlines()
            ]
            self._heard[who] = whole

    def run_until(
        self, condition: Callable[[], bool], timeout: int | None = None
    ) -> bool:
        """Run the platform until `condition()` is true, listening as it goes.

        It is `Platform.run_until` with a `listen()` before each look at
        the condition, so the condition can ask what has been said.
        """

        def heard() -> bool:
            self.listen()
            return condition()

        return self._platform.run_until(heard, timeout)
