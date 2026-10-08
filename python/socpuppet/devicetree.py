"""Generate a devicetree from a platform description.

A devicetree tells firmware (Zephyr, here) what hardware exists and where.
Generating it from the same description that builds the simulation keeps
the two from drifting apart. No simulation is needed to do it.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING

from socpuppet.address_map import Reached, reachable_ports
from socpuppet.components import DeviceNode, cells

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
    # Each component's reachable ports, lowest address first. A component
    # with several, such as a PCIe root complex with its two windows, is
    # one device and gets one node.
    reached: dict[Placed, dict[str, Reached]] = {}
    for found in sorted(
        reachable_ports(connections, view), key=lambda found: found.address
    ):
        reached.setdefault(found.port.placed, {}).setdefault(
            found.port.name, found
        )
    nodes = [
        (placed, node)
        for placed, ports in reached.items()
        if (node := placed.component.device_node(ports)) is not None
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
        f"<{cells(address)} {cells(size)}>" for address, size in node.reg
    )
    first, *rest = node.properties
    lines = [
        f"{indent}{_label(placed.path)}: {node.name}@{node.reg[0][0]:x} {{",
        f"{indent}\t{first}",
        f"{indent}\treg = {reg};",
        *(f"{indent}\t{each}" for each in rest),
    ]
    interrupts = []
    # In the order of the device's own ports, not of the wiring: firmware
    # finds an interrupt by its place in the list.
    ports = placed.component.ports
    for each in sorted(
        (each for each in connections if each.source.placed is placed),
        key=lambda each: ports.index(each.source.name),
    ):
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
