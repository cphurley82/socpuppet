"""Generate a devicetree from a platform description.

A devicetree tells firmware (Zephyr, here) what hardware exists and where.
Generating it from the same description that builds the simulation keeps
the two from drifting apart. No simulation is needed to do it.
"""

from __future__ import annotations

import subprocess
from collections.abc import Collection, Iterable, Iterator, Mapping
from typing import TYPE_CHECKING

from socpuppet.address_map import Reached, reachable_ports
from socpuppet.components import DeviceNode, Dialect, cells

if TYPE_CHECKING:
    from socpuppet.placed import Placed, Port
    from socpuppet.platform import Connection

#: The `chosen` role whose device is the console, as Zephyr names it. In
#: Linux's dialect the console is `stdout-path` instead, a path to its node.
_CONSOLE = "zephyr,console"
#: The node every device on the bus is under.
_BUS = "soc"


def generate(
    connections: Collection[Connection],
    view: Port,
    *,
    dialect: Dialect = "zephyr",
    model: str | None = None,
    bootargs: str | None = None,
    initrd: tuple[int, int] | None = None,
) -> str:
    """The devicetree source for the hardware reachable from the port `view`.

    `connections` are the platform's connections.
    Addresses are the ones a bus master at `view` uses. `dialect` is whose
    bindings the tree is in, `model` is the board's name, for the root to
    give, `bootargs` is the command line `chosen` hands an operating
    system, and `initrd` where in memory its initramfs starts and ends.

    Each component describes its own nodes (`Component.device_nodes`),
    most of them one. What is decided here is where the nodes go: the CPU
    under `cpus`, memory at the top, every other device under `soc`, and
    which of them `chosen` and `aliases` point at.
    """
    master = view.placed
    nodes = _nodes(connections, view, dialect)
    addresses = _addresses(connections, view)
    _refuse_one_number_for_two_lines(nodes, connections)
    lines = [
        "/dts-v1/;",
        "",
        "/ {",
        "\t#address-cells = <2>;",
        "\t#size-cells = <2>;",
        *([f'\tmodel = "{model}";'] if model is not None else []),
    ]
    # A stand-in for a CPU runs no firmware, so it has no `cpus` node and
    # nothing to choose or name devices for.
    cpu = master.component.cpu_node(
        label(master.path), _connected_ports(connections, master)
    )
    if cpu is not None:
        lines += ["", *_chosen(nodes, dialect, bootargs, initrd)]
        aliases = _aliases(nodes)
        if aliases:
            lines += ["", *_references("aliases", aliases)]
        lines += ["", *_cpus(cpu, _timebase(connections, master))]
    for each in _devices(
        nodes,
        connections,
        addresses,
        dialect,
        _labels(nodes),
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


def compile(source: str) -> bytes:
    """The devicetree blob dtc, the devicetree compiler, makes of `source`.

    🎓 Firmware reads a devicetree as a blob, the flattened devicetree, and
    not as source: that is what a stage of a boot hands the next one the
    address of. Raises FileNotFoundError, saying how to install it, if dtc
    is not installed, and ValueError with what dtc said if it refuses the
    source.
    """
    try:
        compiled = subprocess.run(
            ["dtc", "-I", "dts", "-O", "dtb", "-o", "-", "-"],
            input=source.encode(),
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as missing:
        raise FileNotFoundError(
            "dtc, the devicetree compiler, is not installed. On Debian and "
            "Ubuntu it is the package device-tree-compiler, and with "
            "Homebrew it is dtc."
        ) from missing
    if compiled.returncode != 0:
        raise ValueError(
            "dtc refused the devicetree: " + compiled.stderr.decode().strip()
        )
    return compiled.stdout


def overlay(
    connections: Collection[Connection],
    view: Port,
    only: Collection[Placed],
) -> str:
    """The devicetree source for the components `only`, as an overlay.

    🎓 An overlay is a piece of devicetree that is laid over another one
    and adds to it. This one has the nodes of the components named, and
    what `chosen` and `aliases` say of them, for a devicetree that already
    has the rest of what `generate` describes.
    """
    # An overlay is for a Zephyr board's shield.
    nodes = _nodes(connections, view, "zephyr")
    addresses = _addresses(connections, view)
    _refuse_one_number_for_two_lines(nodes, connections)
    roles = {
        role: (placed, node)
        for role, (placed, node) in _roles(nodes).items()
        if placed in only
    }
    blocks = _devices(
        [(placed, node) for placed, node in nodes if placed in only],
        connections,
        addresses,
        "zephyr",
        _labels(nodes),
    )
    aliases = {
        name: (placed, node)
        for name, (placed, node) in _aliases(nodes).items()
        if placed in only
    }
    if aliases:
        blocks.insert(0, _references("aliases", aliases))
    if roles:
        blocks.insert(0, _references("chosen", roles))
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
    connections: Collection[Connection], view: Port, dialect: Dialect
) -> list[tuple[Placed, DeviceNode]]:
    """Each node of each component reachable from `view`, and its component."""
    # Each component's reachable ports, lowest address first. A component
    # with several, such as a PCIe root complex with its two windows, is
    # one device and gets one node, unless it says it is more.
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
        for node in placed.component.device_nodes(
            ports, dialect=dialect, label=label(placed.path)
        )
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
    dialect: Dialect,
    labels: Mapping[tuple[Placed, int], str],
    soc_properties: tuple[str, ...] = (),
) -> list[list[str]]:
    """The nodes where they go: memory at the top, the rest under `soc`.

    Each entry is one node at the top of the tree, as its lines.
    `soc_properties` are the `soc` node's own, for a tree that does not
    have the node yet.
    """
    devices = [
        _node(placed, node, connections, addresses, dialect, labels, depth=1)
        for placed, node in nodes
        if not node.on_bus
    ]
    on_bus = [(placed, node) for placed, node in nodes if node.on_bus]
    if on_bus:
        soc = [f"\t{_BUS} {{", *(f"\t\t{each}" for each in soc_properties)]
        for placed, node in on_bus:
            if len(soc) > 1:
                soc.append("")
            soc += _node(
                placed, node, connections, addresses, dialect, labels, depth=2
            )
        devices.append([*soc, "\t};"])
    return devices


def _node(
    placed: Placed,
    node: DeviceNode,
    connections: Collection[Connection],
    addresses: Mapping[tuple[Placed, str], int],
    dialect: Dialect,
    labels: Mapping[tuple[Placed, int], str],
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
        f"{indent}{_label(placed, node)}: {_name(node)} {{",
        f"{indent}\t{first}",
        *([f"{indent}\treg = {reg};"] if node.reg else []),
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
        found = sink.component.interrupt_input(
            each.sink.name, label(sink.path), dialect=dialect
        )
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
        page = _message_taker(
            getattr(placed, node.messages), connections, addresses, dialect
        )
        if page is not None:
            lines += [f"{indent}\tmsi-parent = <&{labels[page]}>;"]
    for child in node.children:
        lines += _node(
            placed, child, connections, addresses, dialect, labels, depth + 1
        )
    return [*lines, f"{indent}}};"]


def _refuse_one_number_for_two_lines(
    nodes: list[tuple[Placed, DeviceNode]],
    connections: Collection[Connection],
) -> None:
    """Raise if two controllers that send messages have a line of one number.

    A controller that interrupts with messages on its devices' behalf, an
    APLIC, has numbered inputs, and a platform may have several, each
    with an input of every number. Firmware that knows an interrupt by
    one number, as Zephyr does, has each line sent as the identity of its
    input's number, and finds the controller for a number by which one
    has a line there. Two with a line at the same number it could not
    tell apart.
    """
    lines: dict[int, Port] = {}
    controllers = {placed for placed, node in nodes if node.messages}
    for source, sink, _ in connections:
        if sink.placed not in controllers:
            continue
        number = sink.placed.component.interrupt_number(sink.name)
        if number is None:
            continue
        other = lines.setdefault(number, source)
        if other is not source:
            raise ValueError(
                f"{other.path} and {source.path} are both interrupt "
                f"{number}: each is at source {number} of a controller of "
                "its own, and firmware that knows an interrupt by one "
                "number could not tell them apart. Connect one of them to "
                "a source of another number."
            )


def _message_taker(
    sender: Port,
    connections: Collection[Connection],
    addresses: Mapping[tuple[Placed, str], int],
    dialect: Dialect,
) -> tuple[Placed, int] | None:
    """What takes the interrupt messages sent from `sender`, for firmware.

    The component, and the address of the page they reach, which is where
    its node for that page is. It is found the way an address map is, by
    following the sender's own accesses, so it is there only if the
    messages can get there. None if they reach nothing that takes messages
    for the firmware of `dialect` and has a node in this tree. `addresses`
    is where each port is for the master the tree is for.
    """
    for found in reachable_ports(connections, sender):
        taker = found.port.placed
        if not taker.component.takes_messages(found.port.name, dialect=dialect):
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
        return taker, for_firmware
    return None


def _timebase(connections: Collection[Connection], cpu: Placed) -> int | None:
    """How fast the count the CPU reads as `time` goes up, if it has one."""
    for each in connections:
        if each.source.placed is cpu:
            sink = each.sink
            frequency = sink.placed.component.timebase_frequency(sink.name)
            if frequency is not None:
                return frequency
    return None


def _cpus(cpu: tuple[str, ...], timebase: int | None) -> list[str]:
    """The `cpus` node, around the one CPU's own node.

    `timebase` is how many times a second its `time` register counts, if
    it has one to read.
    """
    return [
        "\tcpus {",
        "\t\t#address-cells = <1>;",
        "\t\t#size-cells = <0>;",
        *(
            [f"\t\ttimebase-frequency = <{timebase}>;"]
            if timebase is not None
            else []
        ),
        "",
        *(f"\t\t{each}" if each else "" for each in cpu),
        "\t};",
    ]


def _chosen(
    nodes: list[tuple[Placed, DeviceNode]],
    dialect: Dialect,
    bootargs: str | None,
    initrd: tuple[int, int] | None,
) -> list[str]:
    """The `chosen` node: what firmware uses, its command line, its initramfs.

    Zephyr's names each device it chooses by reference. Linux's names the
    console only, by the path to its node, in `stdout-path`. 🐧 Linux reads
    the initramfs's start and end as numbers of as many cells as each has.
    """
    if dialect == "zephyr":
        chosen = _naming(_roles(nodes))
    else:
        console = _roles(nodes).get(_CONSOLE)
        chosen = (
            [] if console is None else [f'stdout-path = "{_path(console[1])}";']
        )
    if bootargs is not None:
        chosen.insert(0, f'bootargs = "{bootargs}";')
    if initrd is not None:
        start, end = initrd
        chosen += [
            f"linux,initrd-start = <{cells(start)}>;",
            f"linux,initrd-end = <{cells(end)}>;",
        ]
    return ["\tchosen {", *(f"\t\t{each}" for each in chosen), "\t};"]


def _name(node: DeviceNode) -> str:
    """A node's name, with the address of its first registers after `@`."""
    return f"{node.name}@{node.reg[0][0]:x}" if node.reg else node.name


def _labels(
    nodes: list[tuple[Placed, DeviceNode]],
) -> dict[tuple[Placed, int], str]:
    """The label of each node that has registers, by its component and where.

    Where is the address of the node's first registers, which for a page is
    where the firmware finds the page: the address `_message_taker` gives.
    So what is sent to a page names that page's node, for a component with
    a node for each of its pages.
    """
    return {
        (placed, node.reg[0][0]): _label(placed, node)
        for placed, node in nodes
        if node.reg
    }


def _label(placed: Placed, node: DeviceNode) -> str:
    """A node's label: its component's, and the node's suffix, if any."""
    return f"{label(placed.path)}{node.suffix}"


def _path(node: DeviceNode) -> str:
    """Where a node is in the tree: under `soc` if it is on the bus."""
    return f"/{_BUS}/{_name(node)}" if node.on_bus else f"/{_name(node)}"


#: A node that can be named: its component, and the node itself, which
#: may be a child of the component's node.
type _Named = tuple[Placed, DeviceNode]


def _roles(nodes: list[tuple[Placed, DeviceNode]]) -> dict[str, _Named]:
    """Which node the firmware should use for each `chosen` role."""
    return _first_to_claim(
        ((placed, node), node.chosen) for placed, node in _with_children(nodes)
    )


def _aliases(nodes: list[tuple[Placed, DeviceNode]]) -> dict[str, _Named]:
    """Which node has each name in `aliases`."""
    return _first_to_claim(
        ((placed, node), node.aliases) for placed, node in _with_children(nodes)
    )


def _with_children(
    nodes: list[tuple[Placed, DeviceNode]],
) -> Iterator[_Named]:
    """Each node and then its children, all the way down, nodes first."""
    for placed, node in nodes:
        yield placed, node
        yield from _with_children([(placed, child) for child in node.children])


def _first_to_claim(
    claims: Iterable[tuple[_Named, tuple[str, ...]]],
) -> dict[str, _Named]:
    """Which node has each name: the first to claim it.

    A name is for one node. The nodes come in the order of their
    addresses, so of two that claim a name the one at the lower address
    has it.
    """
    first: dict[str, _Named] = {}
    for named, names in claims:
        for name in names:
            first.setdefault(name, named)
    return first


def _references(name: str, devices: dict[str, _Named]) -> list[str]:
    """A node at the top of the tree whose properties each name a node."""
    return [
        f"\t{name} {{",
        *(f"\t\t{each}" for each in _naming(devices)),
        "\t};",
    ]


def _naming(devices: dict[str, _Named]) -> list[str]:
    """Properties that each name a node by its label, in order of name."""
    return [
        f"{property_} = &{_label(placed, node)};"
        for property_, (placed, node) in sorted(devices.items())
    ]


def label(path: str) -> str:
    """A devicetree label for a component path: `io.ram` becomes `io_ram`."""
    return path.replace(".", "_")
