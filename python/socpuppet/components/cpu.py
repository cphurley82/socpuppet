"""The CPUs: the two RISC-V harts, and 🎭 the scripted stand-in."""

from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Callable, Collection, Mapping
from typing import TYPE_CHECKING, Literal, override

from socpuppet.components.base import (
    Component,
    Dialect,
    Script,
    initiator,
    not_a_parameter,
    wire_in,
)
from socpuppet.components.memory import Rom

if TYPE_CHECKING:
    from socpuppet import _core


#: What a CPU and its stand-in both have: the socket their accesses go out
#: of, and their three inputs.
_CPU_PORTS = (
    initiator("socket"),
    wire_in("irq"),
    wire_in("timer_irq"),
    wire_in("reset"),
)


#: What a RISC-V hart here has besides: where its `time` register is read
#: from (a machine timer's `time`), the supervisor external interrupt, and
#: where its registers that are really an IMSIC's are reached.
_HART_PORTS = (
    *_CPU_PORTS,
    initiator("time", required=False),
    wire_in("supervisor_irq"),
    initiator("csr", required=False),
)


#: The cores a `DbtRiseCpu` can be: what `isa` and `modes` may be together,
#: and at which `xlen`.
_CORES: Mapping[tuple[str, str], tuple[int, ...]] = {
    ("imac", "m"): (32, 64),
    ("gc", "msu"): (64,),
}


class RiscvCpu(Component):
    """What socpuppet's RISC-V CPUs have alike, `DbtRiseCpu` and `QboxCpu`.

    The same ports, the same node in a devicetree, the same interrupt
    numbers and the same checks on an image. `xlen` is the width of its
    registers in bits (XLEN is the RISC-V specification's name for it),
    and `reset_vector` is the address of the first instruction. `isa` and
    `modes` are which instruction sets and privilege modes its core has,
    by RISC-V's letters for them.

    With a `gdb_port`, the CPU listens for a debugger on that TCP port, and
    waits for one to attach before it executes anything. Each CPU of a
    simulation can have one, on a port of its own. ⚠️ A CPU stopped in its
    debugger stops the whole simulation, the other CPUs with it.
    """

    port_specs = _HART_PORTS
    is_bus_master = True

    xlen: int
    reset_vector: int
    gdb_port: int = 0
    # Each kind of CPU says which it has.
    isa: str = dataclasses.field(metadata={"parameter": False})
    modes: str = dataclasses.field(metadata={"parameter": False})

    @override
    def cpu_node(
        self, label: str, connected: Collection[str]
    ) -> tuple[str, ...]:
        # Every RISC-V CPU has an interrupt controller inside it: the
        # handful of interrupt inputs the core itself has. Devices refer to
        # it, not to the CPU, which is why it has a label of its own.
        #
        # A devicetree lists the extensions one by one, and G is short for
        # IMAFD with the two Z extensions, which every core here has.
        # Smcsrind is one more, which a CPU has when it has an IMSIC to
        # reach: the window onto registers another block keeps (`miselect`
        # and `mireg`). ⚠️ The extension's name promises more than the CPU
        # has: five more such windows. It is here because it is what
        # Zephyr's IMSIC driver looks for. Ssaia is the same for a CPU
        # with supervisor mode: that mode's window, the register it claims
        # through (`siselect`, `sireg` and `stopei`) and `stopi`, which
        # says which of its interrupts comes first. It is what Linux's
        # IMSIC driver looks for. ⚠️ Its name promises more too: the
        # priorities software may give interrupts. Smaia, the same for
        # machine mode, is left out: OpenSBI, the one program that wants it,
        # finds it by reading `mtopi` and not from the devicetree.
        reaches_an_imsic = "csr" in connected
        # A CPU with supervisor mode translates addresses, and this one's
        # MMU walks Sv39 page tables and no other kind.
        pages = ('\tmmu-type = "riscv,sv39";',) if "s" in self.modes else ()
        extensions = ", ".join(
            f'"{each}"'
            for each in (
                *self.isa.replace("g", "imafd"),
                "zicsr",
                "zifencei",
                *(("smcsrind",) if reaches_an_imsic else ()),
                *(("ssaia",) if reaches_an_imsic and "s" in self.modes else ()),
            )
        )
        return (
            f"{label}: cpu@0 {{",
            '\tdevice_type = "cpu";',
            '\tcompatible = "riscv";',
            "\treg = <0>;",
            f'\triscv,isa-base = "rv{self.xlen}i";',
            f"\triscv,isa-extensions = {extensions};",
            *pages,
            "",
            f"\t{label}_intc: interrupt-controller {{",
            '\t\tcompatible = "riscv,cpu-intc";',
            "\t\t#address-cells = <0>;",
            "\t\t#interrupt-cells = <1>;",
            "\t\tinterrupt-controller;",
            "\t};",
            "};",
        )

    @override
    def interrupt_number(self, port: str) -> int | None:
        # RISC-V numbers a CPU's interrupts by their bit in its
        # interrupt-pending register: 7 is the machine timer, 11 the
        # machine external interrupt and 9 the supervisor's.
        return {"timer_irq": 7, "irq": 11, "supervisor_irq": 9}.get(port)

    @override
    def interrupt_input(
        self, port: str, label: str, *, dialect: Dialect
    ) -> str | None:
        number = self.interrupt_number(port)
        return None if number is None else f"&{label}_intc {number}"

    @override
    def refuse_image(
        self,
        *,
        image: str,
        xlen: int,
        entry: int,
        path: str,
        what_is_at: Callable[[int], Component | None],
    ) -> None:
        if xlen != self.xlen:
            raise ValueError(
                f"{image} is a {xlen}-bit image, and {path} is a "
                f"{self.xlen}-bit CPU. Build the firmware for a "
                f"{self.xlen}-bit core, or describe the CPU with xlen={xlen}."
            )
        if entry == self.reset_vector:
            return
        if isinstance(what_is_at(self.reset_vector), Rom):
            raise ValueError(
                f"{image} starts at {entry:#x}, and {path} starts executing "
                f"in a boot ROM, at {self.reset_vector:#x}. What `load_elf` "
                "gives this CPU is the ROM's own program (firmware/rom). An "
                "image for the ROM to boot goes in the flash, where the "
                "CPU's system controller says to look: "
                "`platform.poke(<its boot_address>, "
                f'socpuppet.boot_image.wrap("{image}"), '
                "via=<the CPU's socket>)`. Or have the CPU start in RAM, "
                "where `load_elf` puts an image, as a socpuppet board "
                "described with no `boot` does."
            )
        raise ValueError(
            f"{image} starts at {entry:#x}, and {path} starts executing "
            f"at its reset vector, {self.reset_vector:#x}. Link the "
            "firmware to start there, or describe the CPU with "
            f"reset_vector={entry:#x}."
        )


class DbtRiseCpu(RiscvCpu):
    """A RISC-V CPU that runs real firmware.

    The model is DBT-RISE-RISCV (Minres), an instruction-set simulator: it
    executes the firmware's instructions one after another, the way the
    processor would. `xlen` is the width of its registers in bits, 32 or
    64 (XLEN is the RISC-V specification's name for it), and `reset_vector`
    is the address of the first instruction.

    Its GDB server is DBT-RISE's own, and listens from the moment the
    platform is built.

    As it comes it is an RV32IMAC or RV64IMAC core in machine mode only: no
    floating point, and no supervisor or user mode. Build firmware for it
    with `-march=rv32imac_zicsr_zifencei` or `-march=rv64imac_zicsr_zifencei`.

    `isa` is which instruction sets it has, by RISC-V's letters for them:
    the part of `RV64IMAC` after the number. `modes` is which privilege
    modes. `isa="gc", modes="msu"` is RV64GC, with single and double
    precision floating point, and with supervisor and user mode below
    machine mode. That pair, at 64 bits only, and the default pair,
    `isa="imac", modes="m"`, at either width, are the cores there are. Any
    other combination is refused. Firmware built for RV64IMAC runs on the
    RV64GC core unchanged. ⚠️ Unless it uses physical memory protection
    (PMP), which the default core has and the RV64GC one has not.
    """

    implementation = "dbt_rise_cpu"

    isa: Literal["imac", "gc"] = not_a_parameter(default="imac")
    modes: Literal["m", "msu"] = not_a_parameter(default="m")

    def __post_init__(self) -> None:
        if self.xlen not in _CORES.get((self.isa, self.modes), ()):
            raise ValueError(
                f'There is no CPU with xlen={self.xlen}, isa="{self.isa}", '
                f'modes="{self.modes}". The ones there are: '
                + ", and ".join(
                    f'isa="{isa}", modes="{modes}" with xlen='
                    + " or ".join(str(xlen) for xlen in xlens)
                    for (isa, modes), xlens in _CORES.items()
                )
                + "."
            )

    @property
    @override
    def parameters(self) -> dict[str, int]:
        # The simulator takes numbers, so the two strings go as two flags.
        return {
            **super().parameters,
            "floating_point": int(self.isa == "gc"),
            "supervisor_mode": int(self.modes == "msu"),
        }


class QboxCpu(RiscvCpu):
    """A RISC-V CPU that is QEMU's: QBox, Qualcomm's QEMU inside SystemC.

    QEMU translates the firmware's instructions into the host's as it
    meets them, where `DbtRiseCpu` interprets them, so it is many times
    faster, and it is a second hart written by other people: firmware that
    works on one and not the other says which to look at. Only a build of
    socpuppet with QBox has it (tools/build_qbox.py), because QEMU is
    GPL-2.0 and is never in the wheel.

    It is RV64GC with supervisor and user mode, the core `DbtRiseCpu` has
    as `isa="gc", modes="msu"`, and has the same ports. It counts
    128 ns for each instruction, where `DbtRiseCpu` counts 100.
    docs/models/qbox-cpu.md says what else it does differently.

    Its GDB server is QEMU's own, and ⚠️ its port opens when the run starts
    and the CPU is held, not as the platform is built: start the run, then
    attach.
    """

    implementation = "qbox_cpu"

    isa: Literal["gc"] = not_a_parameter(default="gc")
    modes: Literal["msu"] = not_a_parameter(default="msu")

    def __post_init__(self) -> None:
        if self.xlen != 64:
            raise ValueError(
                f"A QboxCpu is a 64-bit CPU, and xlen={self.xlen} was asked "
                "for. A CPU of another width is a DbtRiseCpu."
            )
        if (self.isa, self.modes) != ("gc", "msu"):
            raise ValueError(
                "A QboxCpu is RV64GC with supervisor and user mode: "
                'isa="gc", modes="msu", and '
                f'isa="{self.isa}", modes="{self.modes}" was asked for.'
            )


class ScriptedBusMaster(Component):
    """🎭 Stand-in for a CPU.

    It plays a script of bus operations instead of running firmware.
    `script` is a generator function that yields operations (see
    `socpuppet.ops`). It is called again after each reset, so the script
    starts over. With no script, the master does nothing.
    """

    implementation = "scripted_bus_master"
    port_specs = _CPU_PORTS
    is_bus_master = True

    script: Script | None = not_a_parameter(None, kw_only=False)

    def __post_init__(self) -> None:
        script = self.script
        if script is not None and not inspect.isgeneratorfunction(script):
            if inspect.isgenerator(script):
                raise TypeError(
                    "A script must be a generator function, and this is a "
                    "generator that has already been started. Pass the "
                    "function itself, without calling it: "
                    "ScriptedBusMaster(script), not "
                    "ScriptedBusMaster(script())."
                )
            raise TypeError(
                f"A script must be a generator function, and {script!r} "
                "never yields. Write it as a function that yields operations, "
                "such as `yield sp.write32(address, value)`."
            )

    @override
    def configure(self, native: _core.Platform, path: str) -> None:
        if self.script is not None:
            native.set_script(path, self.script)
