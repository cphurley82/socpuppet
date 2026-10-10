"""Keep the tables in docs/address-map.md equal to what the boards describe.

Usage: uv run python tools/address_map_docs.py {check,write} FILE...

A table in a page sits between two marker comments that name it:

    <!-- address-map:ssd start -->
    <!-- address-map:ssd end -->

`write` puts each table between its markers, as the board descriptions in
python/socpuppet/boards give it. `check` exits non-zero if a page is not
what `write` would leave. tools/lint.py runs `check`, or `write` with
--fix. Nothing is simulated, and the simulator need not be built.
"""

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The package as it is in this checkout, built or not: describing a board
# needs none of the simulator.
sys.path.insert(0, str(REPO / "python"))

from socpuppet.address_map import format_address, format_size  # noqa: E402
from socpuppet.boards import host, io_manager, ssd  # noqa: E402

#: One table's place in a page: its two markers and what is between them.
MARKED = re.compile(
    r"<!-- (?P<name>\S+) start -->\n.*?<!-- (?P=name) end -->\n", re.DOTALL
)
START = re.compile(r"<!-- (\S+) start -->")


def main():
    """Check or write the tables of the pages named. Returns the exit status."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["check", "write"])
    parser.add_argument("pages", nargs="+", type=Path, metavar="FILE")
    args = parser.parse_args()

    known = tables()
    status = 0
    for page in args.pages:
        was = page.read_text()
        problem = what_is_wrong_with(was, known)
        if problem:
            print(f"{page}: {problem}")
            status = 1
            continue
        now = with_tables(was, known)
        if now == was:
            continue
        if args.command == "write":
            page.write_text(now)
        else:
            print(
                f"{page}: a table is not what the boards describe. "
                "`uv run python tools/lint.py --fix` writes it again."
            )
            status = 1
    return status


def with_tables(page, known):
    """A page's text with each marked table as `known` has it."""
    return MARKED.sub(
        lambda marked: (
            f"<!-- {marked['name']} start -->\n\n"
            f"{known[marked['name']]}\n\n"
            f"<!-- {marked['name']} end -->\n"
        ),
        page,
    )


def what_is_wrong_with(page, known):
    """What stops the tables of a page's text being written, or None."""
    asked = START.findall(page)
    whole = [marked["name"] for marked in MARKED.finditer(page)]
    for name in asked:
        if name not in known:
            return (
                f"there is no table called {name}. "
                f"The tables are: {', '.join(known)}."
            )
        if name not in whole:
            return (
                f"the table {name} starts and never ends. After its start "
                f"marker there has to be `<!-- {name} end -->`, on a line "
                "of its own."
            )
    return None


def tables():
    """Each table a page can ask for, by the name in its markers."""
    host_board = host.platform
    # How big the drive is changes nothing in a map.
    with_a_drive = host.host(drive_blocks=1).platform
    ssd_board = ssd.platform
    io_board = io_manager.platform

    def seen_from(platform, view):
        return platform.address_map(platform.port(view))

    return {
        "address-map:host": address_table(host_board.address_map()),
        "address-map:host-drive": address_table(
            only_in(with_a_drive.address_map(), host_board.address_map())
        ),
        "address-map:ssd": address_table(
            seen_from(ssd_board, "ssd.cpu.socket")
        ),
        "address-map:ssd-host": address_table(
            seen_from(ssd_board, "host.cpu.socket")
        ),
        "address-map:io-manager": address_table(
            seen_from(io_board, "io.cpu.socket")
        ),
        "address-map:io-manager-compute": address_table(
            seen_from(io_board, "compute.cpu.socket")
        ),
        "interrupts:host": interrupt_table(host_board.interrupt_map()),
        "interrupts:host-drive": interrupt_table(
            only_in(with_a_drive.interrupt_map(), host_board.interrupt_map())
        ),
        "interrupts:ssd": interrupt_table(ssd_board.interrupt_map()),
        "interrupts:io-manager": interrupt_table(io_board.interrupt_map()),
    }


def only_in(entries, others):
    """The entries that are not among the others, in the order they were in."""
    return [entry for entry in entries if entry not in others]


def address_table(entries):
    """An address map as a Markdown table."""
    return markdown_table(
        ("Address", "Size", "What answers", "Its model", "Through"),
        [
            (
                f"`{format_address(entry.address)}`",
                format_size(entry.size),
                f"`{entry.component}.{entry.port}`",
                model_link(entry.implementation),
                ", then ".join(
                    f"`{window.bus}` from `{format_address(window.address)}`"
                    if window.translates
                    else f"`{window.bus}`, same addresses"
                    for window in entry.windows
                ),
            )
            for entry in entries
        ],
    )


def interrupt_table(entries):
    """An interrupt map as a Markdown table."""
    return markdown_table(
        ("Controller", "Number", "Line"),
        [
            (f"`{entry.controller}`", str(entry.number), f"`{entry.line}`")
            for entry in entries
        ],
    )


def markdown_table(header, rows):
    """A table in Markdown, with no line after the last."""
    return "\n".join(
        "|" + "".join(f" {cell} |" if cell else " |" for cell in cells)
        for cells in (header, ["---"] * len(header), *rows)
    )


def model_link(implementation):
    """A link to a model's page in docs/models, with the page's own title.

    A page is named after the model. The two ends of a link share the
    link's page.
    """
    name = implementation.replace("_", "-")
    if not (REPO / "docs/models" / f"{name}.md").exists():
        name = name.removesuffix("-endpoint")
    title = (REPO / "docs/models" / f"{name}.md").read_text().splitlines()[0]
    return f"[{title.removeprefix('# ')}](models/{name}.md)"


if __name__ == "__main__":
    sys.exit(main())
