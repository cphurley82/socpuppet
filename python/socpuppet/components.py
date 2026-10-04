"""The catalogue of components a platform can be described with.

Each class here describes one implementation in the C++ registry: its name
there, its parameters and its ports. Describing a platform uses only these
classes, so it works without loading the simulator.
"""

import inspect


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

    def routes(self):
        """Where an access arriving at this component can go next.

        Yields (output port, base): an access at `base` comes out of that
        port as address 0. A component that answers accesses itself, like a
        memory, yields nothing.
        """
        return ()


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

    def routes(self):
        return (("initiator", 0),)


class ScriptedBusMaster(Component):
    """🎭 Stand-in for a CPU: plays a script of bus operations instead of running firmware.

    `script` is a generator function that yields operations (see
    `socpuppet.ops`). It is called again after each reset, so the script
    starts over. With no script, the master does nothing.
    """

    implementation = "scripted_bus_master"
    ports = ("socket", "irq", "reset")

    def __init__(self, script=None):
        super().__init__()
        if script is not None and not inspect.isgeneratorfunction(script):
            if inspect.isgenerator(script):
                raise TypeError(
                    "A script must be a generator function, and this is a generator "
                    "that has already been started. Pass the function itself, "
                    "without calling it: ScriptedBusMaster(script), not "
                    "ScriptedBusMaster(script())."
                )
            raise TypeError(
                f"A script must be a generator function, and {script!r} never yields. "
                "Write it as a function that yields operations, such as "
                "`yield sp.write32(address, value)`."
            )
        self.script = script

    def configure(self, native, path):
        if self.script is not None:
            native.set_script(path, self.script)


class Router(Component):
    """An address decoder: sends each access to the target mapped at its address.

    The model is `scc::router` from SystemC-Components. Map targets onto it
    with `map()` on the placed router.
    """

    implementation = "router"

    def __init__(self):
        self._ranges = []  # (base, size, label), one per output

    @property
    def ports(self):
        return ("target", *(f"out{index}" for index in range(len(self._ranges))))

    @property
    def parameters(self):
        # The address map, flattened to the name -> number form the simulator
        # takes: "outputs", then "out<N>.base" and "out<N>.size" per output.
        flat = {"outputs": len(self._ranges)}
        for index, (base, size, _) in enumerate(self._ranges):
            flat[f"out{index}.base"] = base
            flat[f"out{index}.size"] = size
        return flat

    def routes(self):
        for index, (base, _, _) in enumerate(self._ranges):
            yield f"out{index}", base

    def add_output(self, base, size, label):
        """Add an output for the range [base, base + size) and return its port name.

        `label` says what the range leads to, for error messages.
        """
        for other_base, other_size, other_label in self._ranges:
            if base < other_base + other_size and other_base < base + size:
                raise ValueError(
                    f"{label} at {base:#x}..{base + size - 1:#x} overlaps "
                    f"{other_label} at {other_base:#x}..{other_base + other_size - 1:#x}. "
                    "Each address can lead to only one target."
                )
        self._ranges.append((base, size, label))
        return f"out{len(self._ranges) - 1}"
