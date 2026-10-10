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
import functools
import sys
from pathlib import Path

import generated

REPO = Path(__file__).resolve().parents[1]

# The package as it is in this checkout, built or not: describing a board
# needs none of the simulator.
sys.path.insert(0, str(REPO / "python"))

from socpuppet.address_map import format_address, format_size  # noqa: E402
from socpuppet.boards import host, io_manager, manager, ssd  # noqa: E402


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
    wanted, placed, problems = generated.pages(args.pages, known)
    problems += [
        f"{page}: there is no table called {name}. "
        f"The tables are: {', '.join(known)}."
        for name, page in placed.items()
        if name not in known
    ]
    for problem in problems:
        print(problem)
    status = generated.settle(args.command, wanted, "the boards")
    return 1 if problems else status


def tables():
    """Each table a page can ask for, by the name in its markers."""
    host_board = host.platform
    # How big the drive is changes nothing in a map.
    with_a_drive = host.host(drive_blocks=1).platform
    # The SSD comes in whole NAND blocks, and one is the least.
    with_the_ssd = host.host(
        drive_blocks=ssd.DRIVE_BLOCKS_PER_NAND_BLOCK, drive=ssd.add_ssd
    ).platform
    # 🎭 The script for a manager has no kit around it, so its map is the
    # manager's with nothing of a CPU's in it.
    with_a_manager = host.host(
        manager=functools.partial(
            manager.add_manager, script=manager.stand_in_manager().script
        )
    ).platform
    ssd_board = ssd.platform
    io_board = io_manager.platform

    def seen_from(platform, view):
        return platform.address_map(platform.port(view))

    return {
        "address-map:host": address_table(host_board.address_map()),
        "address-map:host-drive": address_table(
            only_in(with_a_drive.address_map(), host_board.address_map())
        ),
        "address-map:host-manager": address_table(
            seen_from(with_a_manager, "io.manager.cpu.socket")
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
        "interrupts:host-ssd": interrupt_table(with_the_ssd.interrupt_map()),
        "interrupts:ssd": interrupt_table(ssd_board.interrupt_map()),
        "interrupts:io-manager": interrupt_table(io_board.interrupt_map()),
    }


def only_in(entries, others):
    """The entries that are not among the others, in the order they were in."""
    return [entry for entry in entries if entry not in others]


def address_table(entries):
    """An address map as a Markdown table."""
    return generated.markdown_table(
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
    return generated.markdown_table(
        ("Controller", "Number", "Line"),
        [
            (f"`{entry.controller}`", str(entry.number), f"`{entry.line}`")
            for entry in entries
        ],
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
