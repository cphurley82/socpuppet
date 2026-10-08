"""Generate a devicetree from a platform description.

A devicetree tells firmware (Zephyr, here) what hardware exists and where.
Generating it from the same description that builds the simulation keeps
the two from drifting apart. No simulation is needed to do it.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING

from socpuppet.address_map import reachable_ports
from socpuppet.components import DeviceNode

if TYPE_CHECKING:
    from socpuppet.placed import Placed, Port
    from socpuppet.platform import Connection


def generate(connections: Collection[Connection], view: Port) -> str:
    """The devicetree source for the hardware reachable from the port `view`.

    `connections` are the platform's connections.
    Addresses are the ones a bus master at `view` uses.

    Each component describes its own node (`Component.device_node`). What
    is decided here is where the nodes go: the CPU under `cpus`, memory at
    the top, every other device under `soc`, and which of them `chosen`
    points at.
    """
    master = view.placed
    nodes = [
        (port.placed, node)
        for base, port in sorted(
            reachable_ports(connections, view), key=lambda found: found[0]
        )
        if (node := port.placed.component.device_node(base)) is not None
    ]
    lines = [
        "/dts-v1/;",
        "",
        "/ {",
        "\t#address-cells = <2>;",
        "\t#size-cells = <2>;",
    ]
    # A stand-in for a CPU runs no firmware, so it has no `cpus` node and
    # nothing to choose devices for.
    cpu = master.component.cpu_node(_label(master.path))
    if cpu is not None:
        lines += ["", *_chosen(nodes), "", *_cpus(cpu)]
    for placed, node in nodes:
        if not node.on_bus:
            lines += ["", *_node(placed, node, connections, depth=1)]
    on_bus = [(placed, node) for placed, node in nodes if node.on_bus]
    if on_bus:
        lines += [
            "",
            "\tsoc {",
            '\t\tcompatible = "simple-bus";',
            "\t\t#address-cells = <2>;",
            "\t\t#size-cells = <2>;",
            "\t\tranges;",
        ]
        for placed, node in on_bus:
            lines += ["", *_node(placed, node, connections, depth=2)]
        lines += ["\t};"]
    lines += ["};", ""]
    return "\n".join(lines)


def _node(
    placed: Placed,
    node: DeviceNode,
    connections: Collection[Connection],
    depth: int,
) -> list[str]:
    """One device's node, with its interrupt read off the wire connections."""
    indent = "\t" * depth
    reg = ", ".join(
        f"<{_cells(address)} {_cells(size)}>" for address, size in node.reg
    )
    first, *rest = node.properties
    lines = [
        f"{indent}{_label(placed.path)}: {node.name}@{node.reg[0][0]:x} {{",
        f"{indent}\t{first}",
        f"{indent}\treg = {reg};",
        *(f"{indent}\t{each}" for each in rest),
    ]
    interrupts = []
    for each in connections:
        if each.source.placed is not placed:
            continue
        sink = each.sink.placed
        found = sink.component.interrupt_input(
            each.sink.name, _label(sink.path)
        )
        if found is not None:
            interrupts.append(found)
    if interrupts:
        lines += [f"{indent}\tinterrupts-extended = <{' '.join(interrupts)}>;"]
    return [*lines, f"{indent}}};"]


def _cpus(cpu: tuple[str, ...]) -> list[str]:
    """The `cpus` node, around the one CPU's own node."""
    return [
        "\tcpus {",
        "\t\t#address-cells = <1>;",
        "\t\t#size-cells = <0>;",
        "",
        *(f"\t\t{each}" if each else "" for each in cpu),
        "\t};",
    ]


def _chosen(nodes: list[tuple[Placed, DeviceNode]]) -> list[str]:
    """The `chosen` node: which devices the firmware should use for what.

    The first device that can fill a role gets it.
    """
    filled: dict[str, str] = {}
    for placed, node in nodes:
        for role in node.chosen:
            filled.setdefault(role, _label(placed.path))
    return [
        "\tchosen {",
        *(f"\t\t{role} = &{label};" for role, label in sorted(filled.items())),
        "\t};",
    ]


def _label(path: str) -> str:
    """A devicetree label for a component path: `io.ram` becomes `io_ram`."""
    return path.replace(".", "_")


def _cells(value: int) -> str:
    """A 64-bit value as two 32-bit devicetree cells, high half first."""
    return f"{value >> 32:#x} {value & 0xFFFF_FFFF:#x}"
