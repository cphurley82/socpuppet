"""socpuppet: a whole SoC simulated in SystemC, with Python pulling the strings."""

from socpuppet.components import Memory, PassThroughLink, Router, ScriptedBusMaster
from socpuppet.platform import Platform
from socpuppet.time import ns, us

__all__ = ["Memory", "PassThroughLink", "Platform", "Router", "ScriptedBusMaster", "ns", "us"]
