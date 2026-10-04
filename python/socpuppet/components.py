"""The catalogue of components a platform can be described with.

Each class here describes one implementation in the C++ registry: its name
there, its parameters and its ports. Describing a platform uses only these
classes, so it works without loading the simulator.
"""


class Component:
    """One block of a platform, as described (not yet built)."""

    #: The name of the implementation in the C++ registry.
    implementation: str
    #: The names of the component's ports.
    ports: tuple[str, ...]

    def __init__(self, **parameters):
        self.parameters = parameters

    def configure(self, native, path):
        """Hand the built component anything its parameters cannot carry."""


class Memory(Component):
    """A flat RAM of `size` bytes."""

    implementation = "memory"
    ports = ("socket",)

    def __init__(self, *, size):
        super().__init__(size=size)


class PassThroughLink(Component):
    """🎭 Stand-in for the die-to-die link: passes every transaction on, unchanged."""

    implementation = "pass_through_link"
    ports = ("target", "initiator")


class ScriptedBusMaster(Component):
    """🎭 Stand-in for a CPU: plays a script of bus operations.

    `writes` is a list of (address, 32-bit value) pairs, written in order.
    """

    implementation = "scripted_bus_master"
    ports = ("socket",)

    def __init__(self, *, writes):
        super().__init__()
        self.writes = list(writes)

    def configure(self, native, path):
        native.set_writes(path, self.writes)
