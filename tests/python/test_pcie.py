"""The Python PCIe host stand-in, finding a drive behind a root complex.

host ─▶ bus ─┬─▶ ram
 ▲      ▲    ├─▶ msi receiver ──▶ host's interrupt
 │      │    ├─▶ root complex (configuration window)
 │      │    └─▶ root complex (memory window)
 │      └─────── root complex (the drive's own accesses)
 │
 └── root complex ══ endpoint ─▶ behavioral NVMe
"""

import json

import pytest

import socpuppet as sp

RAM_BASE = 0x8000_0000
RAM_SIZE = 0x10_0000
MSI_BASE = 0x2000_0000
ECAM_BASE = 0x3000_0000
ECAM_SIZE = 0x10_0000
WINDOW_BASE = 0x4000_0000
WINDOW_SIZE = 0x10_0000
NVME_CLASS = 0x01_08_02


def host_with_a_drive(script, blocks=64):
    """A scripted host with an NVMe drive behind a PCIe root complex.

    It is described and not yet built.
    """
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster(script))
    bus = platform.add("bus", sp.Router())
    ram = platform.add("ram", sp.Memory(size=RAM_SIZE))
    msi = platform.add("msi", sp.MsiReceiver())
    rc = platform.add("rc", sp.PcieRootComplex())
    nvme = platform.add("nvme", sp.BehavioralNvme(blocks=blocks))
    endpoint = platform.add(
        "endpoint",
        sp.PcieEndpoint(
            vendor_id=0x5350,
            device_id=0xC0DE,
            class_code=NVME_CLASS,
            function_size=sp.BehavioralNvme.mapped_size,
            vectors=2,
        ),
    )
    platform.connect(cpu.socket, bus.target)
    bus.map(ram.socket, base=RAM_BASE)
    bus.map(msi.socket, base=MSI_BASE)
    bus.map(rc.ecam, base=ECAM_BASE, size=ECAM_SIZE)
    bus.map(rc.mmio, base=WINDOW_BASE, size=WINDOW_SIZE)
    platform.connect(rc.dma, bus.add_input())
    platform.connect(msi.irq, cpu.irq)
    platform.connect(rc.to_device, endpoint.from_host)
    platform.connect(endpoint.to_host, rc.from_device)
    platform.connect(endpoint.bar0, nvme.bar0)
    platform.connect(nvme.dma, endpoint.dma)
    platform.connect(nvme.irq0, endpoint.irq0)
    platform.connect(nvme.irq1, endpoint.irq1)
    return platform


class TestWhenARootComplexsMemoryWindowIsMapped:
    def test_the_description_says_where_the_host_sees_it(self):
        # The root complex works the address out from where its window is
        # mapped, and a saved description has to hold it to be complete.
        platform = host_with_a_drive(script=None)

        components = json.loads(platform.to_json())["components"]

        assert components["rc"]["parameters"]["mmio_base"] == WINDOW_BASE


class TestWhenARootComplexsMemoryWindowIsMappedNowhere:
    def test_building_is_refused_and_the_error_names_the_port_to_map(self):
        platform = sp.Platform()
        platform.add("cpu", sp.ScriptedBusMaster())
        platform.add("rc", sp.PcieRootComplex())

        with pytest.raises(ValueError, match=r"rc\.mmio"):
            platform.build()

    def test_the_description_cannot_be_saved_either(self):
        platform = sp.Platform()
        platform.add("cpu", sp.ScriptedBusMaster())
        platform.add("rc", sp.PcieRootComplex())

        with pytest.raises(ValueError, match=r"rc\.mmio"):
            platform.to_json()


class TestWhenTwoBusMastersSeeARootComplexsMemoryWindowAtDifferentAddresses:
    def test_building_is_refused_and_the_error_names_both_views(self):
        # The second master is on the far side of the link, where the
        # window is at its offset on that die and not at the address the
        # host sees it at.
        platform = sp.Platform()
        host = platform.add("host", sp.ScriptedBusMaster())
        manager = platform.add("manager", sp.ScriptedBusMaster())
        host_bus = platform.add("host_bus", sp.Router())
        io_bus = platform.add("io_bus", sp.Router())
        link = platform.link("link", sp.PassThroughLink())
        rc = platform.add("rc", sp.PcieRootComplex())
        platform.connect(host.socket, host_bus.target)
        host_bus.map(link.a.target, base=0x3000_0000, size=0x1000_0000)
        platform.connect(link.b.initiator, io_bus.target)
        platform.connect(manager.socket, io_bus.add_input())
        io_bus.map(rc.mmio, base=0x0800_0000, size=WINDOW_SIZE)

        with pytest.raises(ValueError, match="different addresses") as error:
            platform.build()

        for part in (
            "host.socket",
            "0x38000000",
            "manager.socket",
            "0x8000000",
        ):
            assert part in str(error.value)


@pytest.mark.platform
class TestWhenTheWindowIsMappedAfterABuildWasRefusedForIt:
    def test_the_next_build_gets_as_far_as_the_simulator(self):
        # A refused description must not use up the process's one
        # simulator, or putting it right would be no use.
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        bus = platform.add("bus", sp.Router())
        rc = platform.add("rc", sp.PcieRootComplex())
        platform.connect(cpu.socket, bus.target)
        bus.map(rc.ecam, base=ECAM_BASE, size=ECAM_SIZE)
        with pytest.raises(ValueError, match="mmio"):
            platform.build()

        bus.map(rc.mmio, base=WINDOW_BASE, size=WINDOW_SIZE)

        # The simulator is created and has its say, about the ports this
        # short description leaves unbound.
        with pytest.raises(RuntimeError, match="not bound"):
            platform.build()
