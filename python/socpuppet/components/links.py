"""The links between the dies, and 🎭 the pass-through stand-in."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, ClassVar, Protocol, override

from socpuppet.components.base import (
    Component,
    DeviceNode,
    Dialect,
    initiator,
    target,
    wire_out,
)
from socpuppet.regs import ucie_link

if TYPE_CHECKING:
    from socpuppet.address_map import Reached


class PassThroughLinkEndpoint(Component):
    """🎭 One end of a pass-through link.

    `Platform.link()` places these in pairs.
    """

    implementation = "pass_through_link_endpoint"
    # The die's side may be left unconnected in either direction. The other
    # side is the other endpoint.
    port_specs = (
        target("target", required=False),
        initiator("initiator", required=False),
        initiator("peer_initiator"),
        target("peer_target"),
    )

    @override
    def routes(self, port: str) -> Iterable[tuple[str, int, int | None]]:
        # Out to the other endpoint, or in from it.
        return (
            (("peer_initiator", 0, None),)
            if port == "target"
            else (("initiator", 0, None),)
        )


class D2dLinkEndpoint(Component):
    """One end of the die-to-die (D2D) link, in the style of UCIe.

    `Platform.link()` places these in pairs. There are two paths between
    the dies, as there are on real hardware. The mainband (`target` and
    `initiator`) is the wide one that carries the dies' traffic, and it
    carries nothing until the link has been trained. The sideband is the
    narrow management one, which is up from the start: `sideband` is the
    link's own registers, as this die's firmware reaches them.

    `reset` is the line this end holds on its own die until the other die
    writes a zero to this end's reset register, and `irq` is how the link
    tells this die's firmware that something has happened.
    """

    implementation = "d2d_link_endpoint"
    #: What the register block takes, which is UCIe's Link DVSEC and the
    #: blocks it points at: as much as its register map says.
    REGISTERS_SIZE: ClassVar[int] = ucie_link.SIZE
    # Everything on the die's own side is optional: a die may only send,
    # only receive, or leave the link's registers unmapped. Both peer
    # sides are the other endpoint.
    port_specs = (
        target("target", required=False),
        initiator("initiator", required=False),
        initiator("peer_initiator"),
        target("peer_target"),
        target("sideband", required=False),
        initiator("sideband_peer_initiator"),
        target("sideband_peer_target"),
        wire_out("reset", required=False),
        wire_out("irq", required=False),
    )

    #: How long the link takes to carry anything across.
    latency_ns: int = 20
    #: How many bytes of it go in a nanosecond.
    bytes_per_ns: int = 16
    #: How long training takes, once UCIe's 4 ms reset hold is over.
    training_ns: int = 1_000_000

    @override
    def size_at(self, port: str) -> int | None:
        # Only the registers have a size of their own. A window onto the
        # other die is as big as whoever maps it says.
        return self.REGISTERS_SIZE if port == "sideband" else None

    @override
    def routes(self, port: str) -> Iterable[tuple[str, int, int | None]]:
        if port == "target":
            return (("peer_initiator", 0, None),)
        if port == "peer_target":
            return (("initiator", 0, None),)
        # The registers are where an access stops, not something it
        # crosses.
        return ()

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode | None:
        registers = reached.get("sideband")
        if registers is None:
            return None
        return DeviceNode(
            "ucie-link",
            ((registers.address, self.REGISTERS_SIZE),),
            (
                'compatible = "socpuppet,ucie-link";',
                # Zephyr's reset controller class: one number names which
                # line to let go, and this link has one, the other die.
                "#reset-cells = <1>;",
            ),
        )


class LinkModel(Protocol):
    """A kind of link, which `Platform.link()` can place."""

    def endpoint(self) -> Component:
        """A new endpoint, for one end of the link."""
        ...

    def peer_pairs(self) -> Iterable[tuple[str, str]]:
        """The ports that join two endpoints, as (source, sink) names.

        `Platform.link()` connects each pair in both directions.
        """
        ...


@dataclasses.dataclass(frozen=True, kw_only=True)
class D2dLink:
    """The die-to-die link, in the style of UCIe.

    Hand it to `Platform.link()`. It has to be trained before its mainband
    carries anything, which the firmware on one of the dies does through
    the link's registers (`D2dLinkEndpoint`).

    💡 The times are plain numbers of nanoseconds: `latency_ns` is how long
    a crossing takes, `bytes_per_ns` how wide the link is, and
    `training_ns` how long SBINIT to ACTIVE takes after UCIe's 4 ms reset
    hold.
    """

    latency_ns: int = D2dLinkEndpoint.latency_ns
    bytes_per_ns: int = D2dLinkEndpoint.bytes_per_ns
    training_ns: int = D2dLinkEndpoint.training_ns

    def endpoint(self) -> Component:
        """A new endpoint, for one end of the link."""
        return D2dLinkEndpoint(
            latency_ns=self.latency_ns,
            bytes_per_ns=self.bytes_per_ns,
            training_ns=self.training_ns,
        )

    def peer_pairs(self) -> Iterable[tuple[str, str]]:
        """The mainband and the sideband, each joining the two ends."""
        return (
            ("peer_initiator", "peer_target"),
            ("sideband_peer_initiator", "sideband_peer_target"),
        )


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

    def peer_pairs(self) -> Iterable[tuple[str, str]]:
        """Just the one path: everything crosses the same way."""
        return (("peer_initiator", "peer_target"),)
