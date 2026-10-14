"""The speed spike's tables, made from the lines in results/ (milestone M26).

Run with the standard library only, from the top of the repository:

    python3 -I spikes/speed/collect.py spikes/speed/results

It prints the Markdown tables that docs/speed-spike.md quotes: where each
CPU was built and run, how fast it ran each loop, how long a developer
waits on each machine, what each backend passed, and the projection of a
boot. A line it cannot place stops it, with the file and the line.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# The environments, in the order the report's columns are in, with the
# header each column has.
ENVIRONMENTS: dict[str, str] = {
    "native-macos-x86_64": "Mac Pro, macOS",
    "docker-amd64-on-macpro": "Mac Pro, Docker x86-64",
    "native-macos-arm64": "Air, macOS",
    "docker-arm64-on-air": "Air, Docker arm64",
    "docker-amd64-rosetta-on-air": "Air, Docker x86-64 (Rosetta)",
    "native-linux-x86_64": "Ubuntu box, Linux",
    "docker-amd64-on-ubuntu": "Ubuntu box, Docker x86-64",
}

# The CPUs, in the order of the report's rows.
CPUS: dict[str, str] = {
    "interp": "DBT-RISE interpreter",
    "asmjit": "DBT-RISE asmjit",
    "qbox-deterministic": "QBox, repeatable",
    "qbox-threaded": "QBox, threaded",
}
# DBT-RISE's LLVM backend has a row for each LLVM it was built against,
# named as run.sh names it: llvm-19 (Debian's), llvm@22 (Homebrew's).
LLVM = re.compile(r"^llvm[-@](\d+)$")


def cpu_name(cpu: str) -> str:
    """The name a row of the tables has."""
    match = LLVM.match(cpu)
    return f"DBT-RISE LLVM {match.group(1)}" if match else CPUS[cpu]


def cpus(results: Results) -> list[str]:
    """Every row, in the order of the tables: LLVM after asmjit."""
    llvms = sorted(
        {cpu for cpu, _ in results.cells if LLVM.match(cpu)},
        key=lambda cpu: int(LLVM.match(cpu).group(1)),  # type: ignore[union-attr]
    )
    return ["interp", "asmjit", *llvms, "qbox-deterministic", "qbox-threaded"]


# The loops, and the quantum each is read at: the counted loop at M1's
# quantum is shown only where it differs.
LOOPS: tuple[str, ...] = ("counted", "hits", "walks")
BOARDS_QUANTUM_US = 100.0
# What a cell of a table says when there is nothing to say.
NOTHING = "-"


class UnplacedLineError(Exception):
    """A line of results/ that the tables have no place for."""


@dataclass
class Cell:
    """What is known of one CPU in one environment."""

    rates: dict[str, list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )
    walk_rates: list[float] = field(default_factory=list)
    reason: str | None = None
    built: bool = False


@dataclass
class Results:
    """Every line of results/, sorted into what the tables need."""

    cells: dict[tuple[str, str], Cell] = field(
        default_factory=lambda: defaultdict(Cell)
    )
    loops: dict[str, dict[str, Any]] = field(default_factory=dict)
    suites: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    sizes: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    boots: list[dict[str, Any]] = field(default_factory=list)
    machines: dict[str, str] = field(default_factory=dict)


def cpu_of(line: dict[str, Any]) -> str:
    """The row a line belongs to."""
    if line.get("cpu") == "qbox":
        return f"qbox-{line['mode']}"
    backend = str(
        line.get("backend") or line.get("default_backend") or "interp"
    )
    return str(line.get("llvm") or backend) if backend == "llvm" else backend


def place(results: Results, line: dict[str, Any], where: str) -> None:
    """Puts one line where the tables will find it."""
    status = line.get("status", "speed")
    if status == "boot":
        results.boots.append(line)
        return
    env = line.get("env")
    if env not in ENVIRONMENTS:
        raise UnplacedLineError(
            f"{where}: the environment {env!r} is not one of "
            + ", ".join(ENVIRONMENTS)
        )
    if "cpu_model" in line:
        results.machines[env] = (
            f"{line['cpu_model']}, {line['threads']} threads"
        )
    cpu = cpu_of(line)
    if cpu not in CPUS and not LLVM.match(cpu):
        raise UnplacedLineError(
            f"{where}: the CPU {cpu!r} is not one of {', '.join(CPUS)}"
        )
    cell = results.cells[(cpu, env)]
    if status == "speed":
        cell.built = True
        if line["loop"] not in LOOPS:
            raise UnplacedLineError(
                f"{where}: the loop {line['loop']!r} is not one of "
                + ", ".join(LOOPS)
            )
        if (
            float(line.get("quantum_us", BOARDS_QUANTUM_US))
            != BOARDS_QUANTUM_US
        ):
            return
        cell.rates[line["loop"]].append(float(line["mips"]))
        if line["loop"] == "walks" and line.get("walks"):
            cell.walk_rates.append(
                float(line["walks"]) / float(line["seconds"]) / 1e6
            )
    elif status == "loop":
        if cpu == "interp" and not line.get("backends"):
            results.loops[env] = line
    elif status == "suite":
        results.suites[(cpu, env)] = line
    elif status == "sizes":
        results.sizes[(cpu, env)] = line
        cell.built = True
    elif status in (
        "not-built",
        "not-tried",
        "configure-failed",
        "build-failed",
        "speed-failed",
    ):
        cell.reason = f"{status}: {line.get('reason', '')}".rstrip(": ")
    else:
        raise UnplacedLineError(
            f"{where}: the status {status!r} is not one the tables know"
        )


def read(directory: Path) -> Results:
    """Every line of every .jsonl file in `directory`."""
    results = Results()
    for path in sorted(directory.glob("*.jsonl")):
        for number, text in enumerate(path.read_text().splitlines(), start=1):
            if text.strip():
                place(results, json.loads(text), f"{path.name}:{number}")
    return results


def median(values: list[float]) -> str:
    """The median to one decimal place, or a dash."""
    return f"{statistics.median(values):.1f}" if values else NOTHING


def table(header: list[str], rows: list[list[str]]) -> str:
    """A Markdown table."""
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def matrix(results: Results) -> str:
    """Which CPU ran in which environment, and why not where it did not."""
    rows = []
    for cpu in cpus(results):
        row = [cpu_name(cpu)]
        for env in ENVIRONMENTS:
            cell = results.cells.get((cpu, env))
            if cell is None:
                row.append("🚧")
            elif cell.rates:
                suite = results.suites.get((cpu, env))
                passed = ""
                if suite and suite["tests"]:
                    ran = suite["tests"]
                    passed = f" suite {ran - suite['failed']}/{ran}"
                row.append("✅" + passed)
            elif cell.reason:
                row.append(f"❌ {cell.reason}")
            else:
                row.append("🚧")
        rows.append(row)
    return table(["CPU", *ENVIRONMENTS.values()], rows)


def speeds(results: Results) -> str:
    """Median millions of instructions a second, per loop, per cell."""
    rows = []
    for env, env_name in ENVIRONMENTS.items():
        for cpu in cpus(results):
            cell = results.cells.get((cpu, env))
            if cell is None or not cell.rates:
                continue
            runs = (
                min(len(cell.rates[loop]) for loop in LOOPS if cell.rates[loop])
                if cell.rates
                else 0
            )
            rows.append(
                [
                    env_name,
                    cpu_name(cpu),
                    *(median(cell.rates[loop]) for loop in LOOPS),
                    median(cell.walk_rates),
                    str(runs),
                ]
            )
    return table(
        [
            "Where",
            "CPU",
            "Counted (M/s)",
            "Hits (M/s)",
            "Walks (M/s)",
            "Walks (M walks/s)",
            "Runs",
        ],
        rows,
    )


def development(results: Results) -> str:
    """What a developer waits for, per environment, with the interpreter."""
    rows = []
    for env, env_name in ENVIRONMENTS.items():
        loop = results.loops.get(env)
        suite = results.suites.get(("interp", env))
        if loop is None and suite is None:
            continue
        rows.append(
            [
                env_name,
                results.machines.get(env, ""),
                f"{loop['full_build_s']:.0f}" if loop else NOTHING,
                f"{loop['incremental_s']:.1f}" if loop else NOTHING,
                f"{suite['suite_s']:.0f}" if suite else NOTHING,
                f"{suite['tests'] - suite['failed']} of {suite['tests']}"
                if suite
                else NOTHING,
            ]
        )
    return table(
        [
            "Where",
            "Machine",
            "Build from nothing (s)",
            "Rebuild after one file (s)",
            "dev suite (s)",
            "Tests passed",
        ],
        rows,
    )


def failures(names: str) -> str:
    """What failed, short: how many C++ tests, and the rest by name.

    A C++ test's name has a dot in it (Suite.Test), and the rest are the
    Python suite, the examples and the tooling, which are few.
    """
    if not names:
        return "none"
    cpp = [name for name in names.split() if "." in name]
    other = [name for name in names.split() if "." not in name]
    parts = [f"{len(cpp)} C++ tests"] if cpp else []
    return ", ".join(parts + other)


def backends(results: Results) -> str:
    """What each backend passed, and what it added, where it was tried."""
    rows = []
    for (cpu, env), suite in sorted(results.suites.items()):
        if cpu == "interp":
            continue
        size = results.sizes.get((cpu, env), {})
        base = results.sizes.get(("interp", env), {})
        added = (
            f"{(size['extension_bytes'] - base['extension_bytes']) / 1e6:+.1f}"
            if "extension_bytes" in size and "extension_bytes" in base
            else NOTHING
        )
        rows.append(
            [
                cpu_name(cpu),
                ENVIRONMENTS[env],
                f"{suite['tests'] - suite['failed']} of {suite['tests']}",
                failures(suite.get("failed_names", "")),
                added,
            ]
        )
    return table(
        ["CPU", "Where", "dev suite passed", "Failed", "Extension, MB more"],
        rows,
    )


def projection(results: Results) -> str:
    """A boot's instructions at each measured rate."""
    if not results.boots:
        return "No boot was counted."
    counts = [int(boot["instructions"]) for boot in results.boots]
    count = statistics.median(counts)
    rows = []
    for env, env_name in ENVIRONMENTS.items():
        for cpu in cpus(results):
            cell = results.cells.get((cpu, env))
            if cell is None or not cell.rates["walks"]:
                continue
            fast = statistics.median(cell.rates["counted"]) * 1e6
            slow = statistics.median(cell.rates["walks"]) * 1e6
            rows.append(
                [
                    env_name,
                    cpu_name(cpu),
                    f"{count / fast:.0f}",
                    f"{count / slow:.0f}",
                ]
            )
    # Plain QEMU, where the count was taken, is the ceiling: its wall time
    # is what the same boot took there, not a projection.
    for env, env_name in ENVIRONMENTS.items():
        walls = [
            float(boot["wall_s"])
            for boot in results.boots
            if boot["env"] == env
        ]
        if walls:
            rows.append(
                [
                    env_name,
                    "Plain QEMU, as measured",
                    f"{statistics.median(walls):.1f}",
                    median([]),
                ]
            )
    header = (
        f"A boot to the shell is {count / 1e6:.0f} million instructions "
        f"(median of {len(counts)})."
    )
    return (
        header
        + "\n\n"
        + table(
            [
                "Where",
                "CPU",
                "At the counted rate (s)",
                "At the walking rate (s)",
            ],
            rows,
        )
    )


def main(argv: list[str]) -> int:
    """Prints every table, or says which line could not be placed."""
    directory = (
        Path(argv[1]) if len(argv) > 1 else Path(__file__).parent / "results"
    )
    try:
        results = read(directory)
    except UnplacedLineError as error:
        print(f"collect.py: {error}", file=sys.stderr)
        return 1
    for title, text in (
        ("Where each CPU ran", matrix(results)),
        ("Speed", speeds(results)),
        ("The development loop", development(results)),
        ("The backends", backends(results)),
        ("The projection", projection(results)),
    ):
        print(f"### {title}\n\n{text}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
