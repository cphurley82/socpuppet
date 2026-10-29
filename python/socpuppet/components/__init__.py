"""The catalogue of components a platform can be described with.

Each class here describes one implementation in the C++ registry: its name
there, its parameters and its ports. Describing a platform uses only these
classes, so it works without loading the simulator. They live in a module
for each area (`base` has `Component` itself, and `cpu`, `memory`,
`storage`, `interrupts`, `peripherals`, `virtio`, `links` and `pcie` the
rest), and every one is a name of this package.

A component's parameters are its fields, written as a dataclass's are, and
its ports are a tuple of `PortSpec`:

    class MachineTimer(Component):
        implementation = "machine_timer"
        port_specs = (target("socket"), wire_out("irq"))

        frequency_hz: int = 10_000_000
"""

from socpuppet.components.base import (
    Component,
    DeviceNode,
    Dialect,
    PortSpec,
    Script,
    cells,
    initiator,
    not_a_parameter,
    target,
    wire_in,
    wire_out,
)
from socpuppet.components.cpu import (
    DbtRiseCpu,
    QboxCpu,
    RiscvCpu,
    ScriptedBusMaster,
)
from socpuppet.components.interrupts import Aplic, Imsic, MsiReceiver, Plic
from socpuppet.components.links import (
    D2dLink,
    D2dLinkEndpoint,
    LinkModel,
    PassThroughLink,
    PassThroughLinkEndpoint,
)
from socpuppet.components.memory import Memory, Rom, Router
from socpuppet.components.pcie import (
    Iommu,
    PcieEndpoint,
    PcieFunctionFront,
    PciemHost,
    PcieRootComplex,
)
from socpuppet.components.peripherals import (
    PERIPHERAL_CLOCK_HZ,
    Gpio,
    I2cController,
    MachineTimer,
    Ns16550,
    Rtc,
    SpiFlash,
    SystemController,
    Watchdog,
)
from socpuppet.components.storage import (
    BehavioralNvme,
    DmaEngine,
    FlashController,
    IdealNand,
    NvmeFrontend,
)
from socpuppet.components.virtio import (
    Virtio9p,
    VirtioBlk,
    VirtioChild,
    VirtioConsole,
    VirtioFs,
    VirtioNet,
    VirtioRng,
    virtio_node,
)

__all__ = [
    "PERIPHERAL_CLOCK_HZ",
    "Aplic",
    "BehavioralNvme",
    "Component",
    "D2dLink",
    "D2dLinkEndpoint",
    "DbtRiseCpu",
    "DeviceNode",
    "Dialect",
    "DmaEngine",
    "FlashController",
    "Gpio",
    "I2cController",
    "IdealNand",
    "Imsic",
    "Iommu",
    "LinkModel",
    "MachineTimer",
    "Memory",
    "MsiReceiver",
    "Ns16550",
    "NvmeFrontend",
    "PassThroughLink",
    "PassThroughLinkEndpoint",
    "PcieEndpoint",
    "PcieFunctionFront",
    "PcieRootComplex",
    "PciemHost",
    "Plic",
    "PortSpec",
    "QboxCpu",
    "RiscvCpu",
    "Rom",
    "Router",
    "Rtc",
    "Script",
    "ScriptedBusMaster",
    "SpiFlash",
    "SystemController",
    "Virtio9p",
    "VirtioBlk",
    "VirtioChild",
    "VirtioConsole",
    "VirtioFs",
    "VirtioNet",
    "VirtioRng",
    "Watchdog",
    "cells",
    "initiator",
    "not_a_parameter",
    "target",
    "virtio_node",
    "wire_in",
    "wire_out",
]
