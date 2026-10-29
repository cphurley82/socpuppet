"""Memory, the boot ROM, and the router between them and the rest."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, override

from socpuppet.components.base import (
    Component,
    DeviceNode,
    Dialect,
    PortSpec,
    initiator,
    target,
)
from socpuppet.placed import PlacedRouter

if TYPE_CHECKING:
    from socpuppet.address_map import Reached
    from socpuppet.platform import Platform


class Memory(Component):
    """A flat RAM of `size` bytes."""

    implementation = "memory"
    port_specs = (target("socket"),)

    size: int

    def __post_init__(self) -> None:
        self.mapped_size = self.size

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode:
        socket = reached["socket"]
        size = (
            self.size if socket.limit is None else min(self.size, socket.limit)
        )
        return DeviceNode(
            "memory",
            # A memory mapped through a smaller range is, to the firmware, a
            # memory of that size.
            ((socket.address, size),),
            ('device_type = "memory";',),
            on_bus=False,
            chosen=("zephyr,sram",),
        )


class Rom(Component):
    """A read-only memory of `size` bytes: what a CPU boots from.

    A CPU starts at a fixed address, its reset vector, and on a real chip
    that address is in a ROM, written when the chip is made, whose program
    finds the firmware and starts it. Map `socket` at the reset vector and
    load the ROM's own program with `platform.load_elf`, before the first
    run. A write from the bus always fails. ⚠️ `poke` and `load_elf` work
    only until the bus master's first access. After it they are refused,
    as a debugger cannot patch a ROM on a board.

    It has no devicetree node. Firmware is not told of the ROM that
    started it.
    """

    implementation = "rom"
    port_specs = (target("socket"),)

    size: int

    def __post_init__(self) -> None:
        self.mapped_size = self.size

    @override
    def why_a_poke_was_refused(self, path: str) -> str:
        return (
            f'"{path}" is a ROM, and its bus master has already come to '
            "it. A ROM is loaded before the first run and not after: a "
            "debugger cannot patch one on a board either."
        )


class Router(Component):
    """An address decoder.

    It sends each access to the target mapped at its address. The model is
    `scc::router` from SystemC-Components. Map targets onto it with `map()`
    and give a second source of accesses an input of its own with
    `add_input()`, both on the placed router.
    """

    implementation = "router"

    def __post_init__(self) -> None:
        self._inputs = 1
        # (base, size, label), one per output
        self._ranges: list[tuple[int, int, str]] = []

    @override
    def place(self, platform: Platform, path: str) -> PlacedRouter:
        return PlacedRouter(platform, path, self)

    @property
    def port_specs(self) -> tuple[PortSpec, ...]:
        """One port per input, then one output port per mapped range.

        The first input is `target`, and the ones added after it are `in1`,
        `in2` and so on.
        """
        return (
            target("target"),
            *(target(f"in{index}") for index in range(1, self._inputs)),
            *(initiator(f"out{index}") for index in range(len(self._ranges))),
        )

    @property
    @override
    def parameters(self) -> dict[str, int]:
        """The address map, flattened to the form the simulator takes.

        That form is name -> number: "inputs" and "outputs", then
        "out<N>.base" and "out<N>.size" per output.
        """
        flat = {"inputs": self._inputs, "outputs": len(self._ranges)}
        for index, (base, size, _) in enumerate(self._ranges):
            flat[f"out{index}.base"] = base
            flat[f"out{index}.size"] = size
        return flat

    @override
    def routes(self, port: str) -> Iterator[tuple[str, int, int | None]]:
        for index, (base, size, _) in enumerate(self._ranges):
            yield f"out{index}", base, size

    def add_input(self) -> str:
        """Add an input for one more source of accesses.

        Returns the input's port name.
        """
        self._inputs += 1
        return f"in{self._inputs - 1}"

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
