"""The catalogue of components a platform can be described with.

Each class here describes one implementation in the C++ registry: its name
there, its parameters and its ports. Describing a platform uses only these
classes, so it works without loading the simulator.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from typing import TYPE_CHECKING, Protocol, override

if TYPE_CHECKING:
    from socpuppet import _core
    from socpuppet.ops import Operation

#: A script: a generator function that yields operations. What a read
#: returned is sent back into the generator. The type asks only for the
#: yields, so a script may be annotated as an Iterator or as any Generator.
Script = Callable[[], Iterator["Operation"]]


class Component(ABC):
    """One block of a platform, as described (not yet built)."""

    #: The name of the implementation in the C++ registry.
    implementation: str

    #: Whether the component is one whose view of memory a peek, a poke or
    #: the devicetree takes: a CPU or its stand-in. A device that only
    #: starts accesses for DMA is not one.
    is_bus_master: bool = False

    #: How many bytes of address space the component answers to, or None
    #: for a component that cannot be mapped onto a router.
    mapped_size: int | None = None

    def __init__(self, **parameters: int) -> None:
        self._parameters = parameters

    @property
    @abstractmethod
    def ports(self) -> tuple[str, ...]:
        """The names of the component's ports."""

    @property
    def parameters(self) -> dict[str, int]:
        """What the implementation is configured with, by name."""
        return self._parameters

    def configure(self, native: _core.Platform, path: str) -> None:
        """Hand the built component anything its parameters cannot carry.

        Most components have nothing to hand over, so this does nothing
        unless a component overrides it.
        """
        return

    def refuse_image(
        self, *, image: str, xlen: int, entry: int, path: str
    ) -> None:
        """Raise if a program image loaded through this component cannot run.

        `image` is the file, built for a word size of `xlen` bits and
        starting at `entry`. `path` is where this component is placed. Most
        components run no program and have no objection.
        """
        return

    def routes(self, port: str) -> Iterable[tuple[str, int]]:
        """Where an access arriving at `port` can go next.

        Yields (output port, base): an access at `base` comes out of that
        port as address 0. A component that answers accesses itself, like a
        memory, yields nothing.
        """
        return ()


class DbtRiseCpu(Component):
    """A RISC-V CPU that runs real firmware.

    The model is DBT-RISE-RISCV (Minres), an instruction-set simulator: it
    executes the firmware's instructions one after another, the way the
    processor would. `xlen` is the width of its registers in bits, 32 or
    64 (XLEN is the RISC-V specification's name for it), and `reset_vector`
    is the address of the first instruction.

    It is an RV32IMAC or RV64IMAC core in machine mode only: no floating
    point, and no supervisor or user mode. Build firmware for it with
    `-march=rv32imac_zicsr_zifencei` or `-march=rv64imac_zicsr_zifencei`.
    """

    implementation = "dbt_rise_cpu"
    ports = ("socket",)
    is_bus_master = True

    def __init__(self, *, xlen: int, reset_vector: int) -> None:
        super().__init__(xlen=xlen, reset_vector=reset_vector)
        self.xlen = xlen
        self.reset_vector = reset_vector

    @override
    def refuse_image(
        self, *, image: str, xlen: int, entry: int, path: str
    ) -> None:
        if xlen != self.xlen:
            raise ValueError(
                f"{image} is a {xlen}-bit image, and {path} is a "
                f"{self.xlen}-bit CPU. Build the firmware for a "
                f"{self.xlen}-bit core, or describe the CPU with xlen={xlen}."
            )
        if entry != self.reset_vector:
            raise ValueError(
                f"{image} starts at {entry:#x}, and {path} starts executing "
                f"at its reset vector, {self.reset_vector:#x}. Link the "
                "firmware to start there, or describe the CPU with "
                f"reset_vector={entry:#x}."
            )


class Memory(Component):
    """A flat RAM of `size` bytes."""

    implementation = "memory"
    ports = ("socket",)

    def __init__(self, *, size: int) -> None:
        super().__init__(size=size)
        self.mapped_size = size


class Ns16550(Component):
    """A 16550-style UART: the serial port a firmware's console prints through.

    What the firmware transmits is kept, and the placed UART's `output`
    reads it. The model is borrowed from VPV-Peripherals (the PULPino UART).
    Nothing is ever received yet, and the interrupt is not connected.
    """

    implementation = "ns16550"
    ports = ("socket",)
    #: The 16550's eight registers, one byte each.
    mapped_size = 8


class PassThroughLinkEndpoint(Component):
    """🎭 One end of a pass-through link.

    `Platform.link()` places these in pairs.
    """

    implementation = "pass_through_link_endpoint"
    ports = ("target", "initiator", "peer_initiator", "peer_target")

    @override
    def routes(self, port: str) -> Iterable[tuple[str, int]]:
        # Out to the other endpoint, or in from it.
        return (
            (("peer_initiator", 0),)
            if port == "target"
            else (("initiator", 0),)
        )


class LinkModel(Protocol):
    """A kind of link, which `Platform.link()` can place."""

    def endpoint(self) -> Component:
        """A new endpoint, for one end of the link."""
        ...


class PassThroughLink:
    """🎭 Stand-in for the die-to-die link.

    It passes every transaction on, unchanged. Hand it to `Platform.link()`.
    It keeps the real link's shape (one
    endpoint per die, traffic both ways) and leaves out everything else: no
    training, no latency, no errors.
    """

    def endpoint(self) -> Component:
        """A new endpoint, for one end of the link."""
        return PassThroughLinkEndpoint()


class ScriptedBusMaster(Component):
    """🎭 Stand-in for a CPU.

    It plays a script of bus operations instead of running firmware.
    `script` is a generator function that yields operations (see
    `socpuppet.ops`). It is called again after each reset, so the script
    starts over. With no script, the master does nothing.
    """

    implementation = "scripted_bus_master"
    ports = ("socket", "irq", "reset")
    is_bus_master = True

    def __init__(self, script: Script | None = None) -> None:
        super().__init__()
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
        self.script = script

    @override
    def configure(self, native: _core.Platform, path: str) -> None:
        if self.script is not None:
            native.set_script(path, self.script)


class Router(Component):
    """An address decoder.

    It sends each access to the target mapped at its address. The model is
    `scc::router` from SystemC-Components. Map targets onto it with `map()`
    on the placed router.
    """

    implementation = "router"

    def __init__(self) -> None:
        # (base, size, label), one per output
        self._ranges: list[tuple[int, int, str]] = []

    @property
    def ports(self) -> tuple[str, ...]:
        """The target port, then one output port per mapped range."""
        return (
            "target",
            *(f"out{index}" for index in range(len(self._ranges))),
        )

    @property
    def parameters(self) -> dict[str, int]:
        """The address map, flattened to the form the simulator takes.

        That form is name -> number: "outputs", then "out<N>.base" and
        "out<N>.size" per output.
        """
        flat = {"outputs": len(self._ranges)}
        for index, (base, size, _) in enumerate(self._ranges):
            flat[f"out{index}.base"] = base
            flat[f"out{index}.size"] = size
        return flat

    @override
    def routes(self, port: str) -> Iterator[tuple[str, int]]:
        for index, (base, _, _) in enumerate(self._ranges):
            yield f"out{index}", base

    def add_output(self, base: int, size: int, label: str) -> str:
        """Add an output for the range [base, base + size).

        Returns the output's port name. `label` says what the range leads
        to, for error messages.
        """
        for other_base, other_size, other_label in self._ranges:
            if base < other_base + other_size and other_base < base + size:
                other_end = other_base + other_size - 1
                raise ValueError(
                    f"{label} at {base:#x}..{base + size - 1:#x} overlaps "
                    f"{other_label} at {other_base:#x}..{other_end:#x}. "
                    "Each address can lead to only one target."
                )
        self._ranges.append((base, size, label))
        return f"out{len(self._ranges) - 1}"
