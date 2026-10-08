"""socpuppet: a whole SoC in SystemC, with Python pulling the strings."""

from socpuppet.components import (
    BehavioralNvme,
    DbtRiseCpu,
    MachineTimer,
    Memory,
    MsiReceiver,
    Ns16550,
    PassThroughLink,
    PcieEndpoint,
    PcieRootComplex,
    Plic,
    Router,
    ScriptedBusMaster,
)
from socpuppet.errors import BusError, ExpectationFailed, NvmeError, PcieError
from socpuppet.msi_host import MsiHost
from socpuppet.nvme_host import NvmeHost, NvmeNamespace
from socpuppet.ops import (
    Steps,
    expect32,
    read,
    read32,
    wait,
    wait_irq,
    write,
    write32,
)
from socpuppet.pcie_host import PcieFunction, PcieHost
from socpuppet.platform import Platform
from socpuppet.time import ms, ns, us
from socpuppet.trace import TraceRecord
from socpuppet.trace import render as render_trace

__all__ = [
    "BehavioralNvme",
    "BusError",
    "DbtRiseCpu",
    "ExpectationFailed",
    "MachineTimer",
    "Memory",
    "MsiHost",
    "MsiReceiver",
    "Ns16550",
    "NvmeError",
    "NvmeHost",
    "NvmeNamespace",
    "PassThroughLink",
    "PcieEndpoint",
    "PcieError",
    "PcieFunction",
    "PcieHost",
    "PcieRootComplex",
    "Platform",
    "Plic",
    "Router",
    "ScriptedBusMaster",
    "Steps",
    "TraceRecord",
    "expect32",
    "ms",
    "ns",
    "read",
    "read32",
    "render_trace",
    "us",
    "wait",
    "wait_irq",
    "write",
    "write32",
]
