"""The Python catalogue and the C++ registry describe the same components.

Descriptions must load without the simulator, so the catalogue repeats what
the registry knows. These tests keep the two from drifting apart, which is
why they look inside socpuppet._core.
"""

import pytest

import socpuppet as sp
from socpuppet.components import Component, PassThroughLinkEndpoint


def router_with_one_output():
    router = sp.Router()
    router.add_output(base=0, size=0x100, label="example")
    return router


def router_with_two_inputs():
    router = router_with_one_output()
    router.add_input()
    return router


# At least one instance of every catalogue class, with whatever parameters
# it needs. Where a count decides how many ports there are, it is not
# the default, so that the ports are seen to follow it.
EXAMPLES = [
    sp.BehavioralNvme(blocks=64, vectors=3),
    sp.DbtRiseCpu(xlen=64, reset_vector=0x8000_0000),
    sp.MachineTimer(),
    sp.Memory(size=0x100),
    sp.MsiReceiver(),
    sp.Ns16550(),
    PassThroughLinkEndpoint(),
    sp.Plic(),
    router_with_one_output(),
    router_with_two_inputs(),
    sp.ScriptedBusMaster(),
]


class TestAComponentThatDoesNotNameItsPorts:
    def test_cannot_be_created(self):
        with pytest.raises(TypeError, match="ports"):
            Component()


class TestTheCatalogue:
    def test_has_an_example_here_for_every_component_class(self):
        assert {type(example) for example in EXAMPLES} == set(
            Component.__subclasses__()
        )

    @pytest.mark.platform
    def test_names_exactly_the_implementations_the_simulator_has(self):
        from socpuppet import _core

        assert {example.implementation for example in EXAMPLES} == set(
            _core.implementations()
        )

    @pytest.mark.platform
    @pytest.mark.parametrize(
        "example", EXAMPLES, ids=lambda example: example.implementation
    )
    def test_declares_the_ports_the_simulator_creates(self, example):
        from socpuppet import _core

        native = _core.Platform(color_log=False)
        native.add("example", example.implementation, example.parameters)

        assert set(example.ports) == set(native.ports("example"))
