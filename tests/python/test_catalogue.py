"""The Python catalogue and the C++ registry describe the same components.

Descriptions must load without the simulator, so the catalogue repeats what
the registry knows. These tests keep the two from drifting apart, which is
why they look inside socpuppet._core.
"""

import pytest

import socpuppet as sp
from socpuppet.components import Component

# One instance of every catalogue class, with whatever parameters it needs.
EXAMPLES = [
    sp.Memory(size=0x100),
    sp.PassThroughLink(),
    sp.ScriptedBusMaster(writes=[]),
]


class TestTheCatalogue:
    def test_has_an_example_here_for_every_component_class(self):
        assert {type(example) for example in EXAMPLES} == set(Component.__subclasses__())

    @pytest.mark.platform
    def test_names_exactly_the_implementations_the_simulator_has(self):
        from socpuppet import _core

        assert {example.implementation for example in EXAMPLES} == set(_core.implementations())

    @pytest.mark.platform
    @pytest.mark.parametrize("example", EXAMPLES, ids=lambda example: example.implementation)
    def test_declares_the_ports_the_simulator_creates(self, example):
        from socpuppet import _core

        native = _core.Platform()
        native.add("example", example.implementation, example.parameters)

        assert set(example.ports) == set(native.ports("example"))
