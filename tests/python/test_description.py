import json
import os
import subprocess
import sys
import textwrap

import pytest

import socpuppet as sp


class TestWhenAPlatformIsOnlyDescribed:
    def test_the_native_extension_is_never_loaded(self):
        loaded = run_python(
            """
            import sys
            import socpuppet as sp

            platform = sp.Platform()
            cpu = platform.add("cpu", sp.ScriptedBusMaster(writes=[(0x10, 1)]))
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


def run_python(code):
    """Run a snippet in a fresh interpreter and return what it printed."""
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        env={"PYTHONPATH": os.pathsep.join(sys.path)},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class TestWhenAPortThatDoesNotExistIsNamed:
    def test_the_error_lists_the_ports_the_component_has(self):
        link = sp.Platform().add("link", sp.PassThroughLink())

        with pytest.raises(AttributeError) as error:
            link.tarket

        assert "target" in str(error.value)
        assert "initiator" in str(error.value)


class TestWhenADescriptionIsDumpedAsJson:
    def test_it_lists_each_component_and_connection(self):
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster(writes=[]))
        ram = platform.add("ram", sp.Memory(size=0x100))
        platform.connect(cpu.socket, ram.socket)

        assert json.loads(platform.to_json()) == {
            "components": {
                "cpu": {"implementation": "scripted_bus_master", "parameters": {}},
                "ram": {"implementation": "memory", "parameters": {"size": 0x100}},
            },
            "connections": [{"source": "cpu.socket", "sink": "ram.socket"}],
        }


class TestWhenAComponentIsAddedThroughAGroup:
    def test_its_path_carries_every_group(self):
        platform = sp.Platform()

        ram = platform.group("host").group("io").add("ram", sp.Memory(size=0x100))

        assert ram.path == "host.io.ram"


class TestWhenTwoComponentsAreGivenTheSamePath:
    def test_the_second_is_refused_and_the_error_names_the_path(self):
        platform = sp.Platform()
        platform.group("io").add("ram", sp.Memory(size=0x100))

        with pytest.raises(ValueError) as error:
            platform.group("io").add("ram", sp.Memory(size=0x200))

        assert "io.ram" in str(error.value)
