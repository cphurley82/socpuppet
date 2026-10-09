"""The Python catalogue and the C++ registry describe the same components.

Descriptions must load without the simulator, so the catalogue repeats what
the registry knows. These tests keep the two from drifting apart, which is
why they look inside socpuppet._core.
"""

import pytest

import socpuppet as sp
from socpuppet.components import (
    Component,
    PassThroughLinkEndpoint,
    PortSpec,
)


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
    sp.FlashController(),
    sp.IdealNand(blocks=4),
    sp.MachineTimer(),
    sp.Memory(size=0x100),
    sp.MsiPlicBridge(vectors=3),
    sp.MsiReceiver(),
    sp.Ns16550(),
    PassThroughLinkEndpoint(),
    sp.PcieEndpoint(
        vendor_id=0x5350,
        device_id=0xC0DE,
        class_code=0x010802,
        function_size=0x2000,
        vectors=3,
    ),
    sp.PcieRootComplex(),
    sp.Plic(),
    router_with_one_output(),
    router_with_two_inputs(),
    sp.ScriptedBusMaster(),
]


class TestAComponentThatDoesNotDeclareItsPorts:
    def test_cannot_be_created(self):
        with pytest.raises(TypeError, match="port_specs"):
            Component()


class TestAComponentGivenAParameterItDoesNotTake:
    def test_is_refused_and_the_error_names_the_parameter(self):
        with pytest.raises(TypeError, match="sources"):
            sp.Plic(sources=8)


class TestAComponentsParameters:
    def test_are_what_it_was_created_with_and_its_defaults(self):
        nvme = sp.BehavioralNvme(blocks=64)

        assert nvme.parameters == {"blocks": 64, "vectors": 2}

    def test_leave_out_what_the_simulator_is_not_configured_with(self):
        def script():
            yield sp.wait(sp.ns(1))

        assert sp.ScriptedBusMaster(script).parameters == {}


class TestAPcieEndpointWithANumberOfVectorsMsixCannotHave:
    @pytest.mark.parametrize("vectors", [0, 2049])
    def test_is_refused_and_the_error_gives_the_range(self, vectors):
        with pytest.raises(ValueError, match="1 to 2048"):
            sp.PcieEndpoint(
                vendor_id=0x5350,
                device_id=0xC0DE,
                class_code=0x010802,
                function_size=0x2000,
                vectors=vectors,
            )


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
        "example",
        EXAMPLES,
        ids=lambda example: f"{example.implementation}({len(example.ports)})",
    )
    def test_declares_the_ports_the_simulator_creates_and_their_kinds(
        self, example
    ):
        from socpuppet import _core

        native = _core.Platform(color_log=False)
        # As a platform does: what the component is told outright, and what
        # it works out from where it is. Here every port is at address 0.
        parameters = example.parameters | example.located_parameters(
            "example", lambda port: 0
        )
        native.add("example", example.implementation, parameters)

        assert set(example.port_specs) == {
            PortSpec(*port) for port in native.ports("example")
        }
