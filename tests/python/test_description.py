import json

import pytest

import socpuppet as sp
from processes import run_python


class TestWhenAPlatformIsOnlyDescribed:
    def test_the_native_extension_is_never_loaded(self):
        loaded = run_python(
            """
            import sys
            import socpuppet as sp

            platform = sp.Platform()
            cpu = platform.add("cpu", sp.ScriptedBusMaster())
            ram = platform.add("ram", sp.Memory(size=0x100))
            platform.connect(cpu.socket, ram.socket)

            from importlib.machinery import EXTENSION_SUFFIXES
            print([
                name
                for name, module in sys.modules.items()
                if name.startswith("socpuppet")
                and str(getattr(module, "__file__", "")).endswith(tuple(EXTENSION_SUFFIXES))
            ])
            """
        )

        assert loaded == "[]"


class TestWhenAPortThatDoesNotExistIsNamed:
    def test_the_error_lists_the_ports_the_component_has(self):
        link = sp.Platform().link("link", sp.PassThroughLink())

        with pytest.raises(AttributeError) as error:
            _ = link.a.tarket

        assert "target" in str(error.value)
        assert "initiator" in str(error.value)


class TestWhenADescriptionIsDumpedAsJson:
    def test_it_lists_each_component_and_connection(self):
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        ram = platform.add("ram", sp.Memory(size=0x100))
        platform.connect(cpu.socket, ram.socket)

        assert json.loads(platform.to_json()) == {
            "components": {
                "cpu": {
                    "implementation": "scripted_bus_master",
                    "parameters": {},
                },
                "ram": {
                    "implementation": "memory",
                    "parameters": {"size": 0x100},
                },
            },
            "connections": [
                {"source": "cpu.socket", "sink": "ram.socket", "trace": False}
            ],
            "groups": [],
            "links": [],
            "quantum": sp.us(100),
        }

    def test_it_names_the_groups_and_which_endpoints_make_a_link(self):
        platform = sp.Platform()
        compute = platform.group("compute")
        io = platform.group("io")
        platform.link("d2d", sp.PassThroughLink(), compute, io)
        io.group("storage")

        description = json.loads(platform.to_json())

        assert description["groups"] == ["compute", "io", "io.storage"]
        assert description["links"] == [
            {"name": "d2d", "a": "compute.d2d", "b": "io.d2d"}
        ]

    def test_it_gives_the_quantum_that_was_set(self):
        platform = sp.Platform()
        platform.quantum = sp.ns(250)

        assert json.loads(platform.to_json())["quantum"] == sp.ns(250)


class TestWhenABusPortIsConnectedASecondTime:
    def test_a_second_connection_from_a_master_is_refused(self):
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        ram = platform.add("ram", sp.Memory(size=0x100))
        more_ram = platform.add("more_ram", sp.Memory(size=0x100))
        platform.connect(cpu.socket, ram.socket)

        with pytest.raises(
            ValueError, match=r"cpu\.socket is already connected to ram\.socket"
        ):
            platform.connect(cpu.socket, more_ram.socket)

    def test_a_second_connection_to_a_target_is_refused(self):
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        other_cpu = platform.add("other_cpu", sp.ScriptedBusMaster())
        ram = platform.add("ram", sp.Memory(size=0x100))
        platform.connect(cpu.socket, ram.socket)

        with pytest.raises(
            ValueError, match=r"ram\.socket is already connected to cpu\.socket"
        ):
            platform.connect(other_cpu.socket, ram.socket)


class TestWhenAWireIsConnectedASecondTime:
    def test_one_output_may_drive_several_inputs(self):
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        other_cpu = platform.add("other_cpu", sp.ScriptedBusMaster())
        timer = platform.add("timer", sp.MachineTimer())

        platform.connect(timer.irq, cpu.timer_irq)
        platform.connect(timer.irq, other_cpu.timer_irq)

        assert len(json.loads(platform.to_json())["connections"]) == 2

    def test_a_second_driver_for_one_input_is_refused(self):
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        timer = platform.add("timer", sp.MachineTimer())
        other_timer = platform.add("other_timer", sp.MachineTimer())
        platform.connect(timer.irq, cpu.timer_irq)

        with pytest.raises(
            ValueError,
            match=r"cpu\.timer_irq is already connected to timer\.irq",
        ):
            platform.connect(other_timer.irq, cpu.timer_irq)


class TestWhenAComponentIsAddedThroughAGroup:
    def test_its_path_carries_every_group(self):
        platform = sp.Platform()

        ram = (
            platform.group("host").group("io").add("ram", sp.Memory(size=0x100))
        )

        assert ram.path == "host.io.ram"


class TestWhenTwoComponentsAreGivenTheSamePath:
    def test_the_second_is_refused_and_the_error_names_the_path(self):
        platform = sp.Platform()
        platform.group("io").add("ram", sp.Memory(size=0x100))

        with pytest.raises(ValueError, match=r"io\.ram"):
            platform.group("io").add("ram", sp.Memory(size=0x200))
