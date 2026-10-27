"""The register files under src/vpvper, written by hand, agree with their maps.

A model written for VPV-Peripherals has its register map in SystemRDL, as
VPV's own do, and a register file in the shape MINRES's generator,
peakrdl_mnrs, makes from it. That generator is MINRES's own and is not
available here, so the file is written by hand, and this holds it to the
map: every register at its offset, as wide as the map says, with the map's
fields and its reset value.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pytest
from systemrdl import RDLCompiler
from systemrdl.node import RegNode

VPVPER = Path(__file__).resolve().parents[2] / "src" / "vpvper"


@dataclass(frozen=True)
class Register:
    """One register, as a map or a register file says it is."""

    offset: int
    width: int
    #: Each field's name, lowest bit and width, lowest bit first.
    fields: tuple[tuple[str, int, int], ...]
    reset: int


def from_the_map(rdl: Path) -> dict[str, Register]:
    """The registers a SystemRDL map describes, by name."""
    compiler = RDLCompiler()
    compiler.compile_file(str(rdl))
    root = compiler.elaborate()
    registers = {}
    for node in root.top.descendants():
        if not isinstance(node, RegNode):
            continue
        fields = sorted(node.fields(), key=lambda field: field.lsb)
        registers[node.inst_name] = Register(
            offset=node.absolute_address,
            width=node.get_property("regwidth"),
            fields=tuple((f.inst_name, f.lsb, f.width) for f in fields),
            reset=sum((f.get_property("reset") or 0) << f.lsb for f in fields),
        )
    return registers


def from_the_register_file(header: Path) -> dict[str, Register]:
    """The registers a register file in peakrdl_mnrs's shape declares."""
    text = header.read_text()
    widths = {}
    fields: dict[str, list[tuple[str, int, int]]] = {}
    for name, width, body in re.findall(
        r"BEGIN_BF_DECL\((\w+)_t, uint(\d+)_t\)(.*?)END_BF_DECL\(\)",
        text,
        re.S,
    ):
        widths[name] = int(width)
        fields[name] = [
            (field, int(lsb), int(bits))
            for field, lsb, bits in re.findall(
                r"BF_FIELD\((\w+), (\d+), (\d+)\)", body
            )
        ]
    resets = {
        name: int(reset.rstrip("UL"), 0)
        for name, reset in re.findall(
            r"NAMED\((\w+), r_\w+, (\w+), \*this\)", text
        )
    }
    return {
        name: Register(
            offset=int(offset.rstrip("UL"), 0),
            width=widths[name],
            fields=tuple(sorted(fields[name], key=lambda field: field[1])),
            reset=resets[name],
        )
        for name, offset in re.findall(r"addResource\((\w+), (\w+)\);", text)
    }


MAPS = sorted(VPVPER.glob("*/*.rdl"))


def test_there_are_maps_to_hold_register_files_to() -> None:
    assert MAPS


@pytest.mark.parametrize("rdl", MAPS, ids=[rdl.stem for rdl in MAPS])
def test_a_register_file_written_by_hand_says_what_its_map_says(
    rdl: Path,
) -> None:
    header = rdl.parent / "gen" / f"{rdl.stem}_regs.h"

    assert from_the_register_file(header) == from_the_map(rdl)
