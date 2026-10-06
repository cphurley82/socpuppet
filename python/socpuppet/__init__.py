"""socpuppet: a whole SoC in SystemC, with Python pulling the strings."""

from socpuppet.components import (
    DbtRiseCpu,
    MachineTimer,
    Memory,
    Ns16550,
    PassThroughLink,
    Plic,
    Router,
    ScriptedBusMaster,
)
from socpuppet.errors import ExpectationFailed
from socpuppet.ops import (
    expect32,
    read,
    read32,
    wait,
    wait_irq,
    write,
    write32,
)
from socpuppet.platform import Platform
from socpuppet.time import ms, ns, us
from socpuppet.trace import TraceRecord
from socpuppet.trace import render as render_trace

__all__ = [
    "DbtRiseCpu",
    "ExpectationFailed",
    "MachineTimer",
    "Memory",
    "Ns16550",
    "PassThroughLink",
    "Platform",
    "Plic",
    "Router",
    "ScriptedBusMaster",
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
