"""Keep the Zephyr shields' overlays equal to what the host board describes.

Usage: uv run python tools/shield_overlays.py {check,write} FILE...

A shield is Zephyr's word for hardware plugged into a board, and its
overlay is the devicetree that hardware adds. The shields here whose
hardware is a part of the host board (python/socpuppet/boards/host.py)
have their overlays generated from it. `write` writes each of those named
in FILE as the board gives it; `check` exits non-zero if one is not what
`write` would leave. Other files named are left alone: their shields are
written by hand. tools/lint.py runs `check`, or `write` with --fix.
Nothing is simulated, and the simulator need not be built.
"""

import argparse
import sys
from pathlib import Path

import generated

REPO = Path(__file__).resolve().parents[1]

# The package as it is in this checkout, built or not: describing a board
# needs none of the simulator.
sys.path.insert(0, str(REPO / "python"))

from socpuppet.boards import host  # noqa: E402

#: Each generated shield's overlay, by the shield's name.
OVERLAYS = {
    "socpuppet_host_drive": host.drive_overlay,
    "socpuppet_host_gpio_loopback": host.gpio_loopback_overlay,
    "socpuppet_host_i2c_ram": host.i2c_ram_overlay,
    "socpuppet_host_iommu": host.iommu_overlay,
    "socpuppet_host_spi_loopback": host.spi_loopback_overlay,
    "socpuppet_host_virtio": host.virtio_overlay,
}


def main() -> int:
    """Check or write the overlays named. Returns the exit status."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["check", "write"])
    parser.add_argument("files", nargs="+", type=Path, metavar="FILE")
    args = parser.parse_args()

    wanted = {
        path: OVERLAYS[path.stem]()
        for path in args.files
        if path.stem in OVERLAYS and path.parent.name == path.stem
    }
    return generated.settle(args.command, wanted, "the board descriptions")


if __name__ == "__main__":
    sys.exit(main())
