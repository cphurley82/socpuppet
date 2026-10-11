"""socpuppet: a whole SoC in SystemC, with Python pulling the strings."""

from socpuppet.components import (
    Aplic,
    BehavioralNvme,
    D2dLink,
    DbtRiseCpu,
    DmaEngine,
    FlashController,
    IdealNand,
    Imsic,
    MachineTimer,
    Memory,
    MsiReceiver,
    Ns16550,
    NvmeFrontend,
    PassThroughLink,
    PcieEndpoint,
    PcieRootComplex,
    Plic,
    Rom,
    Router,
    ScriptedBusMaster,
)
from socpuppet.errors import BusError, ExpectationFailed, NvmeError, PcieError
from socpuppet.io_manager import IoManager
from socpuppet.msi_host import MsiHost
from socpuppet.nvme_host import NvmeHost, NvmeNamespace
from socpuppet.ops import (
    Steps,
    expect32,
    read,
    read32,
    read64,
    wait,
    wait_irq,
    write,
    write32,
    write64,
)
from socpuppet.pcie_host import PcieFunction, PcieHost
from socpuppet.platform import Platform
from socpuppet.ssd_firmware import SsdFirmware
from socpuppet.time import ms, ns, us
from socpuppet.trace import TraceRecord
from socpuppet.trace import render as render_trace
from socpuppet.transcript import Transcript
from socpuppet.transcript import render as render_transcript
from socpuppet.ucie import render_sideband

__all__ = [
    "Aplic",
    "BehavioralNvme",
    "BusError",
    "D2dLink",
    "DbtRiseCpu",
    "DmaEngine",
    "ExpectationFailed",
    "FlashController",
    "IdealNand",
    "Imsic",
    "IoManager",
    "MachineTimer",
    "Memory",
    "MsiHost",
    "MsiReceiver",
    "Ns16550",
    "NvmeError",
    "NvmeFrontend",
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
    "Rom",
    "Router",
    "ScriptedBusMaster",
    "SsdFirmware",
    "Steps",
    "TraceRecord",
    "Transcript",
    "expect32",
    "ms",
    "ns",
    "read",
    "read32",
    "read64",
    "render_sideband",
    "render_trace",
    "render_transcript",
    "us",
    "wait",
    "wait_irq",
    "write",
    "write32",
    "write64",
]
