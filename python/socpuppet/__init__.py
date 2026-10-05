"""socpuppet: a whole SoC in SystemC, with Python pulling the strings."""

from socpuppet.components import (
    DbtRiseCpu,
    Memory,
    Ns16550,
    PassThroughLink,
    Router,
    ScriptedBusMaster,
)
from socpuppet.errors import ExpectationFailed
from socpuppet.ops import expect32, read32, wait, wait_irq, write32
from socpuppet.platform import Platform
from socpuppet.time import ms, ns, us
from socpuppet.trace import TraceRecord
from socpuppet.trace import render as render_trace

__all__ = [
    "DbtRiseCpu",
    "ExpectationFailed",
    "Memory",
    "Ns16550",
    "PassThroughLink",
    "Platform",
    "Router",
    "ScriptedBusMaster",
    "TraceRecord",
    "expect32",
    "ms",
    "ns",
    "read32",
    "render_trace",
    "us",
    "wait",
    "wait_irq",
    "write32",
]
