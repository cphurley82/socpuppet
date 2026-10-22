"""Writes the SSD as Python's board describes it, for spike_pciem_host.

    PYTHONPATH=python uv run python spikes/pciem/describe_ssd.py \
        --blocks 131072 > build/pciem-ssd.board

The SSD is `add_ssd_function`'s, with its own CPU, so that the C++
program builds the same board the Python one would, without a copy kept
by hand. One line each, in order:

    quantum <picoseconds>
    add <path> <implementation> [<parameter>=<value> ...]
    connect <source> <sink>

The uplink is left with nothing mapped onto it, as `add_ssd_function`
leaves it: the program maps the bridge there.
"""

from __future__ import annotations

import argparse
import json

from socpuppet.boards.ssd import add_ssd_function
from socpuppet.platform import Platform


def main() -> None:
    """Print the description of an SSD of `--blocks` blocks."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--blocks", type=int, default=131072)
    blocks = parser.parse_args().blocks
    platform = Platform()
    add_ssd_function(platform, blocks=blocks)
    description = json.loads(platform.to_json())
    print(f"quantum {description['quantum']}")
    for path, component in description["components"].items():
        parameters = " ".join(
            f"{name}={value}" for name, value in component["parameters"].items()
        )
        print(f"add {path} {component['implementation']} {parameters}".rstrip())
    for connection in description["connections"]:
        print(f"connect {connection['source']} {connection['sink']}")


if __name__ == "__main__":
    main()
