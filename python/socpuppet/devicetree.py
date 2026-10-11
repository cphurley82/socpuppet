"""Generate a devicetree from a platform description.

A devicetree tells firmware (Zephyr, here) what hardware exists and where.
Generating it from the same description that builds the simulation keeps
the two from drifting apart. No simulation is needed to do it.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
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
    nodes = _nodes(connections, view)
    lines = [
        "/dts-v1/;",
        "",
        "/ {",
        "\t#address-cells = <2>;",
        "\t#size-cells = <2>;",
    ]
    # A stand-in for a CPU runs no firmware, so it has no `cpus` node and
    # nothing to choose devices for.
    cpu = master.component.cpu_node(
        label(master.path), _connected_ports(connections, master)
    )
    if cpu is not None:
        lines += ["", *_chosen(_roles(nodes)), "", *_cpus(cpu)]
    for each in _devices(
        nodes,
        connections,
        _addresses(connections, view),
        soc_properties=(
            'compatible = "simple-bus";',
            "#address-cells = <2>;",
            "#size-cells = <2>;",
            "ranges;",
        ),
    ):
        lines += ["", *each]
    lines += ["};", ""]
    return "\n".join(lines)


def overlay(
    connections: Collection[Connection],
    view: Port,
    only: Collection[Placed],
) -> str:
    """The devicetree source for the components `only`, as an overlay.

    🎓 An overlay is a piece of devicetree that is laid over another one
    and adds to it. This one has the nodes of the components named, and
    what `chosen` says of them, for a devicetree that already has the rest
    of what `generate` describes.
    """
    nodes = _nodes(connections, view)
    roles = {
        role: placed for role, placed in _roles(nodes).items() if placed in only
    }
    blocks = _devices(
        [(placed, node) for placed, node in nodes if placed in only],
        connections,
        _addresses(connections, view),
    )
    if roles:
        blocks.insert(0, _chosen(roles))
    lines = ["/ {"]
    for block in blocks:
        # A blank line between one block and the next.
        lines += [*([""] if len(lines) > 1 else []), *block]
    lines += ["};", ""]
    return "\n".join(lines)


def _connected_ports(
    connections: Collection[Connection], placed: Placed
) -> set[str]:
    """The names of a component's ports that have something connected."""
    return {
        port.name
        for each in connections
        for port in (each.source, each.sink)
        if port.placed is placed
    }


def _nodes(
    connections: Collection[Connection], view: Port
) -> list[tuple[Placed, DeviceNode]]:
    """Each component reachable from `view` that has a node, and the node."""
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
    return [
        (placed, node)
        for placed, ports in reached.items()
        if (node := placed.component.device_node(ports)) is not None
    ]


def _addresses(
    connections: Collection[Connection], view: Port
) -> dict[tuple[Placed, str], int]:
    """Where each port reachable from `view` is, for a master there.

    A port that is reachable at more than one address is at its lowest, as
    it is in its node.
    """
    addresses: dict[tuple[Placed, str], int] = {}
    for found in sorted(
        reachable_ports(connections, view), key=lambda found: found.address
    ):
        addresses.setdefault(
            (found.port.placed, found.port.name), found.address
        )
    return addresses


def _devices(
    nodes: list[tuple[Placed, DeviceNode]],
    connections: Collection[Connection],
    addresses: Mapping[tuple[Placed, str], int],
    soc_properties: tuple[str, ...] = (),
) -> list[list[str]]:
    """The nodes where they go: memory at the top, the rest under `soc`.

    Each entry is one node at the top of the tree, as its lines.
    `soc_properties` are the `soc` node's own, for a tree that does not
    have the node yet.
    """
    devices = [
        _node(placed, node, connections, addresses, depth=1)
        for placed, node in nodes
        if not node.on_bus
    ]
    on_bus = [(placed, node) for placed, node in nodes if node.on_bus]
    if on_bus:
        soc = ["\tsoc {", *(f"\t\t{each}" for each in soc_properties)]
        for placed, node in on_bus:
            if len(soc) > 1:
                soc.append("")
            soc += _node(placed, node, connections, addresses, depth=2)
        devices.append([*soc, "\t};"])
    return devices


def _node(
    placed: Placed,
    node: DeviceNode,
    connections: Collection[Connection],
    addresses: Mapping[tuple[Placed, str], int],
    depth: int,
) -> list[str]:
    """One device's node, with its interrupt read off the wire connections.

    `addresses` is where each port is for the master the tree is for.
    """
    indent = "\t" * depth
    reg = ", ".join(
        f"<{cells(address)} {cells(size)}>" for address, size in node.reg
    )
    first, *rest = node.properties
    lines = [
        f"{indent}{label(placed.path)}: {node.name}@{node.reg[0][0]:x} {{",
        f"{indent}\t{first}",
        f"{indent}\treg = {reg};",
        *(f"{indent}\t{each}" for each in rest),
    ]
    interrupts = []
    # In the order of the device's own ports, not of the wiring: firmware
    # finds an interrupt by its place in the list.
    ports = placed.component.ports
    for each in sorted(
        (
            each
            for each in connections
            if each.source.placed is placed
            and (node.interrupts is None or each.source.name in node.interrupts)
        ),
        key=lambda each: ports.index(each.source.name),
    ):
        sink = each.sink.placed
        found = sink.component.interrupt_input(each.sink.name, label(sink.path))
        if found is not None:
            interrupts.append(found)
    if interrupts and node.short_interrupts:
        # Each is "&controller" and then the numbers.
        controllers = sorted({each.split()[0] for each in interrupts})
        if len(controllers) > 1:
            raise ValueError(
                f'The devicetree node of "{placed.path}" names its interrupt '
                f"controller once, and its interrupt lines go to "
                f"{' and '.join(controllers)}. Connect them all to one "
                f"controller."
            )
        [controller] = controllers
        numbers = " ".join(
            each.removeprefix(controller + " ") for each in interrupts
        )
        lines += [
            f"{indent}\tinterrupt-parent = <{controller}>;",
            f"{indent}\tinterrupts = <{numbers}>;",
        ]
    elif interrupts:
        lines += [f"{indent}\tinterrupts-extended = <{' '.join(interrupts)}>;"]
    if node.messages is not None:
        taker = _message_taker(
            getattr(placed, node.messages), connections, addresses
        )
        if taker is not None:
            lines += [f"{indent}\tmsi-parent = <&{label(taker.path)}>;"]
    return [*lines, f"{indent}}};"]


def _message_taker(
    sender: Port,
    connections: Collection[Connection],
    addresses: Mapping[tuple[Placed, str], int],
) -> Placed | None:
    """What takes the interrupt messages sent from `sender`, for firmware.

    It is found the way an address map is, by following the sender's own
    accesses, so it is there only if the messages can get there. None if
    they reach nothing that takes messages and has a node in this tree.
    `addresses` is where each port is for the master the tree is for.
    """
    for found in reachable_ports(connections, sender):
        taker = found.port.placed
        if not taker.component.takes_messages(found.port.name):
            continue
        for_firmware = addresses.get((taker, found.port.name))
        if for_firmware is None:
            continue
        if for_firmware != found.address:
            # Firmware reads the address from the taker's node and tells
            # the sender to send there.
            raise ValueError(
                f'"{sender.placed.path}" sends its interrupt messages to '
                f'"{taker.path}", and finds it at {found.address:#x}, where '
                f"the devicetree has it at {for_firmware:#x}. Firmware "
                f"tells the sender the devicetree's address, so the messages "
                f"would go astray. Map the way from {sender.path} so that "
                f"it has the same addresses as the CPU's bus."
            )
        return taker
    return None


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


def _roles(nodes: list[tuple[Placed, DeviceNode]]) -> dict[str, Placed]:
    """Which device fills each `chosen` role: the first that can."""
    filled: dict[str, Placed] = {}
    for placed, node in nodes:
        for role in node.chosen:
            filled.setdefault(role, placed)
    return filled


def _chosen(roles: dict[str, Placed]) -> list[str]:
    """The `chosen` node: which devices the firmware should use for what."""
    return [
        "\tchosen {",
        *(
            f"\t\t{role} = &{label(placed.path)};"
            for role, placed in sorted(roles.items())
        ),
        "\t};",
    ]


def label(path: str) -> str:
    """A devicetree label for a component path: `io.ram` becomes `io_ram`."""
    return path.replace(".", "_")
