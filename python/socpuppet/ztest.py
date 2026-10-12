"""What Zephyr's test framework printed on a console, read as a report."""

from __future__ import annotations

import dataclasses
import re
from typing import Literal, NamedTuple, cast

#: How one case went, in ztest's word for it.
Result = Literal["PASS", "FAIL", "SKIP"]
#: How a whole run went, in the word its last line ends with.
Verdict = Literal["SUCCESSFUL", "FAILED"]

#: 🎓 ztest ends a run with one line that says how all of it went, and
#: that line is what Zephyr's own test runner, twister, judges a run by.
_VERDICT = re.compile(r"PROJECT EXECUTION (SUCCESSFUL|FAILED)")


#: The line a suite begins with.
_SUITE_BEGINS = re.compile(r"Running TESTSUITE (\S+)")
#: The line a case ends with: ` PASS - test_eggs in 0.003 seconds`. It has
#: the case's name and not its suite's, which is the one that is running.
_CASE_ENDS = re.compile(r"(PASS|FAIL|SKIP) - (\S+) in ([\d.]+) seconds")
#: A case in the summary ztest prints when every suite is over:
#: ` - PASS - [suite.case] duration = 0.003 seconds`.
_CASE_IN_THE_SUMMARY = re.compile(
    r"- (PASS|FAIL|SKIP) - \[([^.\]]+)\.([^\]]+)\] duration = ([\d.]+) seconds"
)


class Case(NamedTuple):
    """One test case, and how it went."""

    suite: str
    name: str
    result: Result
    #: How long the case took, as ztest measured it.
    seconds: float


class Suite(NamedTuple):
    """One suite of test cases, and the cases of it that ended."""

    name: str
    #: How many times the suite began. More than once for a suite that
    #: resets its CPU and carries on, as a test of a watchdog does, and
    #: never for a suite that was left out, whose cases the summary still
    #: lists as skipped.
    starts: int
    cases: tuple[Case, ...]


@dataclasses.dataclass(frozen=True)
class Report:
    """How a run of ztest went, as its console told it."""

    suites: tuple[Suite, ...]
    #: None for a console with no verdict: a run that was stopped, or an
    #: image with no test framework in it.
    verdict: Verdict | None

    @property
    def passed(self) -> bool:
        """Whether the run ended with the verdict that nothing failed."""
        return self.verdict == "SUCCESSFUL"

    @property
    def cases(self) -> tuple[Case, ...]:
        """Every suite's cases, in the order they ran."""
        return tuple(case for suite in self.suites for case in suite.cases)

    def suite(self, name: str) -> Suite:
        """The suite called `name`."""
        return _found(name, {each.name: each for each in self.suites}, "suite")

    def case(self, name: str) -> Case:
        """The case called `name`, which is `suite.case` as ztest prints it."""
        return _found(
            name,
            {f"{each.suite}.{each.name}": each for each in self.cases},
            "case",
        )


def _found[Kind](name: str, among: dict[str, Kind], kind: str) -> Kind:
    """The suite or the case called `name`, or an error that says who is."""
    if name not in among:
        raise KeyError(
            f"ztest's console has no {kind} {name}. It has: "
            f"{', '.join(among) or 'none at all'}."
        )
    return among[name]


def parse(console: str) -> Report:
    """Read what a console printed as a report of ztest's run.

    A case is read where it ends, so a run that was stopped still has the
    cases that had ended, and again in the summary, which also has the
    cases of a suite that was left out.
    """
    starts: dict[str, int] = {}
    # Each suite's cases by their names, the suites in the order they were
    # first named.
    cases: dict[str, dict[str, Case]] = {}
    running = ""
    for line in console.splitlines():
        if began := _SUITE_BEGINS.search(line):
            running = began[1]
            starts[running] = starts.get(running, 0) + 1
            cases.setdefault(running, {})
        elif ended := _CASE_ENDS.search(line):
            result, name, seconds = ended.groups()
            cases.setdefault(running, {})[name] = _case(
                running, name, result, seconds
            )
        elif summed_up := _CASE_IN_THE_SUMMARY.search(line):
            result, suite, name, seconds = summed_up.groups()
            cases.setdefault(suite, {})[name] = _case(
                suite, name, result, seconds
            )
    return Report(
        tuple(
            Suite(name, starts.get(name, 0), tuple(its.values()))
            for name, its in cases.items()
        ),
        verdict_of(console),
    )


def _case(suite: str, name: str, result: str, seconds: str) -> Case:
    """A case from the pieces of the line that told of it."""
    return Case(suite, name, cast("Result", result), float(seconds))


def verdict_of(printed: str) -> Verdict | None:
    """The verdict in what was printed, or None if it has none.

    `printed` is one line or many. This is all that a loop which runs an
    image until its tests are over has to ask of each line as it comes.
    """
    verdict = _VERDICT.search(printed)
    return cast("Verdict", verdict[1]) if verdict else None
