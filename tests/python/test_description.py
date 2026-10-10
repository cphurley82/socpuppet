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
            "address_maps": {
                "cpu.socket": [
                    {
                        "address": 0,
                        "size": 0x100,
                        "component": "ram",
                        "port": "socket",
                        "implementation": "memory",
                        "group": None,
                        "windows": [],
                    }
                ]
            },
            "interrupts": [],
        }

    def test_it_has_the_address_map_of_each_bus_master(self):
        platform = sp.Platform()
        for name in ("cpu", "other_cpu"):
            cpu = platform.add(name, sp.ScriptedBusMaster())
            ram = platform.add(f"{name}_ram", sp.Memory(size=0x100))
            platform.connect(cpu.socket, ram.socket)

        maps = json.loads(platform.to_json())["address_maps"]

        assert {
            master: [entry["component"] for entry in entries]
            for master, entries in maps.items()
        } == {"cpu.socket": ["cpu_ram"], "other_cpu.socket": ["other_cpu_ram"]}

    def test_a_window_on_the_way_says_where_it_is_and_whether_it_translates(
        self,
    ):
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        near = platform.add("near", sp.Router())
        far = platform.add("far", sp.Router())
        ram = platform.add("ram", sp.Memory(size=0x10))
        platform.connect(cpu.socket, near.target)
        near.map(far.target, base=0x1000, size=0x800)
        far.map(ram.socket, base=0)

        (entry,) = json.loads(platform.to_json())["address_maps"]["cpu.socket"]

        assert entry["windows"] == [
            {
                "bus": "near",
                "address": 0x1000,
                "size": 0x800,
                "translates": True,
            }
        ]

    def test_it_has_each_interrupt_line_and_its_number(self):
        platform = sp.Platform()
        plic = platform.add("plic", sp.Plic())
        dma = platform.add("dma", sp.DmaEngine())
        platform.connect(dma.irq, plic.source5)

        assert json.loads(platform.to_json())["interrupts"] == [
            {"controller": "plic", "number": 5, "line": "dma.irq"}
        ]

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

    def test_the_real_link_joins_its_mainband_and_its_sideband(self):
        platform = sp.Platform()
        compute = platform.group("compute")
        io = platform.group("io")

        platform.link("d2d", sp.D2dLink(), compute, io)

        connections = json.loads(platform.to_json())["connections"]
        assert [(one["source"], one["sink"]) for one in connections] == [
            ("compute.d2d.peer_initiator", "io.d2d.peer_target"),
            ("io.d2d.peer_initiator", "compute.d2d.peer_target"),
            (
                "compute.d2d.sideband_peer_initiator",
                "io.d2d.sideband_peer_target",
            ),
            (
                "io.d2d.sideband_peer_initiator",
                "compute.d2d.sideband_peer_target",
            ),
        ]

    def test_a_traced_link_records_what_crosses_it_either_way(self):
        platform = sp.Platform()
        compute = platform.group("compute")
        io = platform.group("io")

        platform.link("d2d", sp.D2dLink(), compute, io, trace=True)

        connections = json.loads(platform.to_json())["connections"]
        assert all(one["trace"] for one in connections)

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


class TestWhenAPortIsAskedForByItsPath:
    def test_it_is_the_port_of_the_component_at_that_path(self):
        platform = sp.Platform()
        ram = platform.group("io").add("ram", sp.Memory(size=0x100))

        assert platform.port("io.ram.socket").path == ram.socket.path

    def test_a_component_that_is_not_there_is_refused_with_the_ones_that_are(
        self,
    ):
        platform = sp.Platform()
        platform.add("ram", sp.Memory(size=0x100))

        with pytest.raises(ValueError, match=r"rom\.socket.*ram"):
            platform.port("rom.socket")

    def test_a_port_the_component_lacks_is_refused_with_the_ones_it_has(self):
        platform = sp.Platform()
        platform.add("ram", sp.Memory(size=0x100))

        with pytest.raises(ValueError, match=r"ram\.sockit.*socket"):
            platform.port("ram.sockit")
