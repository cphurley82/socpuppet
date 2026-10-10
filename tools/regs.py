"""Write what is generated from the register maps, or check that it is so.

Usage: uv run python tools/regs.py {check,write} FILE...

🎓 A register map says what a block's registers are: where each one is,
which bits of it mean what, and what firmware may do to them. They are
written once, in SystemRDL (the files in regs/), which is the language
the industry writes them in.

Each file named is compiled. One that describes a block has an `addrmap`
named after the file, and from it comes a C header that the models and
the Zephyr drivers both include. A file with no `addrmap` holds what
other files include, and nothing comes from it.

`write` writes the files. `check` exits non-zero if one is not what
`write` would leave, or if a register map does not compile. tools/lint.py
runs `check`, or `write` with --fix. Run it from the top of the repo.
"""

import argparse
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

from systemrdl import RDLCompileError, RDLCompiler
from systemrdl.component import Addrmap
from systemrdl.rdltypes import OnWriteType

#: Where the C headers go: the one directory that both the simulator's
#: build and a Zephyr build have on their include path, and that is in
#: the wheel, where firmware is built from.
HEADERS = Path("python/socpuppet/zephyr_module/include/socpuppet/regs")

#: How wide generated text is, comments included.
COLUMNS = 78


class Refused(Exception):
    """A register map that compiles and that nothing can be made from."""


@dataclass(frozen=True)
class Told:
    """One of the things a field can be told, or can say: a named value."""

    name: str
    value: int
    what: str | None


@dataclass(frozen=True)
class Field:
    """Some bits of a register that mean one thing."""

    name: str
    low: int
    high: int
    what: str | None
    #: Whether firmware reads it, and writes it.
    readable: bool
    writable: bool
    #: Whether writing a one is what clears it.
    write_one_to_clear: bool
    told: tuple[Told, ...]


@dataclass(frozen=True)
class Register:
    """One register of a block, or several in a row that are one thing."""

    name: str
    offset: int
    #: How many bits wide it is, and how many of it there are in a row.
    width: int
    count: int
    what: str | None
    fields: tuple[Field, ...]

    @property
    def size(self):
        """How many bytes it takes, all of it."""
        return self.count * self.width // 8


@dataclass(frozen=True)
class Block:
    """A block's register map, as its SystemRDL file gives it."""

    #: What the file is called, less `.rdl`, and what it calls the block.
    name: str
    title: str
    what: str | None
    #: The file, as it was named to this tool.
    source: str
    #: How many bytes of address space the block takes.
    size: int
    registers: tuple[Register, ...]


@dataclass(frozen=True)
class Value:
    """A number, as each language that gets it writes it."""

    c: str
    python: str


@dataclass(frozen=True)
class Constant:
    """One name that a generated file gives a number, less the block's own."""

    name: str
    what: str | None
    value: Value


def main():
    """Check or write what the register maps named give. Returns the status."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["check", "write"])
    parser.add_argument("files", nargs="+", metavar="FILE")
    args = parser.parse_args()

    try:
        blocks = [
            block for file in args.files if (block := read(file)) is not None
        ]
    except RDLCompileError:
        # The compiler has said what is wrong, and where.
        return 1
    except Refused as refused:
        print(refused)
        return 1
    status = 0
    for path, text in generated(blocks).items():
        if path.exists() and path.read_text() == text:
            continue
        if args.command == "write":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        else:
            print(
                f"{path} is not what the register maps give. "
                "`uv run python tools/lint.py --fix` writes it again."
            )
            status = 1
    return status


def generated(blocks):
    """What each generated file holds, by its path from the top of the repo."""
    return {HEADERS / f"{block.name}.h": c_header(block) for block in blocks}


def read(file):
    """The block a SystemRDL file describes, or None if it describes none."""
    compiler = RDLCompiler()
    compiler.compile_file(file)
    if not any(
        isinstance(defined, Addrmap)
        for defined in compiler.root.comp_defs.values()
    ):
        return None
    top = compiler.elaborate().top
    name = Path(file).stem
    if top.inst_name != name:
        raise Refused(
            f"{file}: the addrmap is called {top.inst_name}, and what is "
            "generated from a register map is named after its file. Call "
            f"the addrmap {name}, or the file {top.inst_name}.rdl."
        )
    size = top.get_property("block_size", default=None)
    if size is None:
        raise Refused(
            f"{file}: nothing says how big the block is. SystemRDL has no "
            "word for that, so the register maps here have a property of "
            "their own: give the addrmap `block_size = <bytes>;`."
        )
    for register in top.registers(unroll=False):
        if register.raw_address_offset + register.total_size > size:
            raise Refused(
                f"{file}: the register {register.inst_name} ends at "
                f"{register.raw_address_offset + register.total_size:#x}, "
                f"outside the block's {size:#x} bytes. Move it, or make "
                "`block_size` bigger."
            )
    return Block(
        name=name,
        title=top.get_property("name"),
        what=said(top.get_property("desc")),
        source=file,
        size=size,
        registers=tuple(
            Register(
                name=register.inst_name,
                offset=register.raw_address_offset,
                width=register.get_property("regwidth"),
                count=register.array_dimensions[0] if register.is_array else 1,
                what=said(register.get_property("desc")),
                fields=tuple(
                    Field(
                        name=field.inst_name,
                        low=field.low,
                        high=field.high,
                        what=said(field.get_property("desc")),
                        readable=field.is_sw_readable,
                        writable=field.is_sw_writable,
                        write_one_to_clear=(
                            field.get_property("onwrite") == OnWriteType.woclr
                        ),
                        told=tuple(
                            Told(
                                member.name, member.value, said(member.rdl_desc)
                            )
                            for member in field.get_property("encode") or ()
                        ),
                    )
                    for field in register.fields()
                ),
            )
            for register in top.registers(unroll=False)
        ),
    )


def said(description):
    """A description on one line, however the file laid it out."""
    return None if description is None else " ".join(description.split())


def paragraphs(block):
    """Yield the block's constants: its size, and then a register at a time."""
    digits = max(2, len(f"{block.size - 1:X}"))
    yield [
        Constant(
            "SIZE",
            "How many bytes of address space the block takes.",
            hexadecimal(block.size, digits),
        )
    ]
    for register in block.registers:
        constants = [
            Constant(
                register.name,
                register.what,
                hexadecimal(register.offset, digits),
            )
        ]
        if register.count > 1:
            constants.append(
                Constant(
                    f"{register.name}_SIZE",
                    None,
                    hexadecimal(register.size, digits),
                )
            )
        for field in register.fields:
            constants += of_field(field, register)
        yield constants


def of_field(field, register):
    """The constants a field of a register gives.

    A field that is the whole of its register has no bits to name: the
    register's own name is the field's, and what it can be told is named
    after the register.
    """
    if field.high - field.low + 1 == register.width:
        name = register.name
        constants = []
    elif field.high == field.low:
        name = f"{register.name}_{field.name}"
        constants = [Constant(name, field.what, bit(field.low))]
    else:
        name = f"{register.name}_{field.name}"
        mask = ((1 << (field.high - field.low + 1)) - 1) << field.low
        constants = [
            Constant(
                f"{name}_MASK",
                field.what,
                hexadecimal(mask, register.width // 4),
            ),
            Constant(f"{name}_SHIFT", None, number(field.low)),
        ]
    return constants + [
        Constant(f"{name}_{told.name}", told.what, number(told.value))
        for told in field.told
    ]


def hexadecimal(value, digits):
    """A number written in hexadecimal, with at least `digits` digits."""
    return Value(f"0x{value:0{digits}X}U", f"0x{value:0{digits}X}")


def number(value):
    """A number written in decimal."""
    return Value(f"{value}U", str(value))


def bit(position):
    """The number with only the bit at `position` set."""
    return Value(f"(1U << {position})", f"1 << {position}")


def preamble(block):
    """What a generated file says of itself first, a paragraph at a time."""
    return [
        " ".join(filter(None, [f"{block.title}: the registers.", block.what])),
        f"Generated from {block.source} by tools/regs.py. Do not edit: "
        "change the register map and run `uv run python tools/lint.py "
        "--fix`.",
    ]


def c_header(block):
    """The block's C header.

    It has nothing in it but `#define`, each of a number with `U` on it,
    so that C and C++ both take it and neither has anything to say about
    a sign.
    """
    guard = f"SOCPUPPET_REGS_{block.name.upper()}_H_"
    prefix = f"{block.name.upper()}_"
    lines = [
        "/*",
        *(
            f" * {line}".rstrip()
            for line in wrapped("\n\n".join(preamble(block)), COLUMNS - 3)
        ),
        " */",
        "",
        f"#ifndef {guard}",
        f"#define {guard}",
    ]
    for constants in paragraphs(block):
        # One register's names are lined up with each other, as
        # clang-format would have them (AlignConsecutiveMacros).
        width = max(len(constant.name) for constant in constants)
        lines.append("")
        for constant in constants:
            if constant.what is not None:
                lines += c_comment(constant.what)
            lines.append(
                f"#define {prefix}{constant.name:<{width}} {constant.value.c}"
            )
    lines += ["", f"#endif /* {guard} */", ""]
    return "\n".join(lines)


def c_comment(text):
    """A comment's lines: one line if it fits, and a block if it does not."""
    if len(text) <= COLUMNS - len("/*  */"):
        return [f"/* {text} */"]
    return ["/*", *(f" * {line}" for line in wrapped(text, COLUMNS - 3)), " */"]


def wrapped(text, width):
    """Text as lines no longer than `width`, its paragraphs kept apart."""
    lines = []
    for paragraph in text.split("\n\n"):
        lines += [*textwrap.wrap(paragraph, width), ""]
    return lines[:-1]


if __name__ == "__main__":
    sys.exit(main())
