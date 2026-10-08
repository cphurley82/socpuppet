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
from scripts import play

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


@pytest.mark.platform
class TestWhenTheHostScansTheBus:
    def test_it_finds_the_one_function_and_what_it_says_it_is(self):
        found = []

        def script():
            pci = sp.PcieHost(ecam=ECAM_BASE)
            found.extend((yield from pci.scan()))

        platform = host_with_a_drive(script)
        platform.build()

        platform.run()

        assert found == [
            sp.PcieFunction(
                bus=0,
                device=0,
                function=0,
                vendor_id=0x5350,
                device_id=0xC0DE,
                class_code=NVME_CLASS,
            )
        ]


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


@pytest.mark.platform
class TestWhenTheHostPlacesTheDrivesRegisters:
    def test_the_drive_answers_at_the_address_it_was_given(self):
        ready = []

        def script():
            pci = sp.PcieHost(ecam=ECAM_BASE)
            (drive,) = yield from pci.scan()
            registers = WINDOW_BASE + 0x1_0000
            yield from pci.place(drive, registers)
            ready.append((yield from enable_the_controller_at(registers)))

        platform = host_with_a_drive(script)
        platform.build()

        platform.run()

        assert ready == [True]

    def test_an_address_the_drive_cannot_be_at_is_refused(self):
        # A function's registers go at a multiple of the size it asks for,
        # which is at least the size of the drive's own registers.
        def script():
            pci = sp.PcieHost(ecam=ECAM_BASE)
            (drive,) = yield from pci.scan()
            yield from pci.place(
                drive, WINDOW_BASE + sp.BehavioralNvme.mapped_size // 2
            )

        platform = host_with_a_drive(script)
        platform.build()

        with pytest.raises(sp.PcieError, match="multiple of its size"):
            platform.run()


def enable_the_controller_at(registers):
    """Enables an NVMe controller, and returns whether it then says ready.

    CC, the controller's configuration register, is at offset 0x14 and
    CSTS, its status, at 0x1C. Setting the lowest bit of the first enables
    the controller, and the lowest bit of the second then says it is ready.
    """
    yield sp.write32(registers + 0x14, 1)
    status = yield sp.read32(registers + 0x1C)
    return bool(status & 1)


@pytest.mark.platform
class TestWhenThePlatformPeeksAtTheDrivesRegistersThroughTheWindow:
    def test_it_sees_the_controllers_status(self):
        # A peek takes the debugger's path, through the root complex and
        # the endpoint to the drive, and so can GDB.
        def script():
            pci = sp.PcieHost(ecam=ECAM_BASE)
            (drive,) = yield from pci.scan()
            yield from pci.place(drive, WINDOW_BASE)
            yield from enable_the_controller_at(WINDOW_BASE)

        platform = host_with_a_drive(script)
        platform.build()
        platform.run()

        assert platform.peek32(WINDOW_BASE + 0x1C) & 1


@pytest.mark.platform
class TestWhenTheHostRoutesTheDrivesInterruptsToAnMsiReceiver:
    def test_the_nvme_driver_is_woken_by_them(self):
        # The driver waits for an interrupt after every command, so that
        # it learns anything from the drive at all shows they arrive.
        learned = []

        def script():
            pci = sp.PcieHost(ecam=ECAM_BASE)
            msi = sp.MsiHost(receiver=MSI_BASE)
            (drive,) = yield from pci.scan()
            yield from pci.place(drive, WINDOW_BASE)
            yield from pci.route_interrupts(drive, to=msi)
            nvme = sp.NvmeHost(
                registers=WINDOW_BASE, memory=RAM_BASE, interrupt=msi.wait
            )
            yield from nvme.enable()
            learned.append((yield from nvme.identify_namespace()))

        platform = host_with_a_drive(script, blocks=64)
        platform.build()

        platform.run()

        assert [namespace.blocks for namespace in learned] == [64]


# A function for the tests that play the host against a fake bus.
SOME_FUNCTION = sp.PcieFunction(
    bus=0,
    device=3,
    function=0,
    vendor_id=0x5350,
    device_id=0xC0DE,
    class_code=NVME_CLASS,
)


class TestWhenAFunctionHasNoMsixCapability:
    def test_routing_its_interrupts_is_refused_and_the_error_names_it(self):
        # Every register of this function reads as zero, so it says it has
        # no capabilities at all.
        pci = sp.PcieHost(ecam=ECAM_BASE)
        msi = sp.MsiHost(receiver=MSI_BASE)

        with pytest.raises(sp.PcieError, match=r"00:03\.0"):
            play(pci.route_interrupts(SOME_FUNCTION, to=msi), lambda _: 0)

    def test_a_list_of_other_capabilities_is_searched_to_its_end_first(self):
        # A list of one capability (identifier 0x01, power management) that
        # points on to nothing.
        function = FakeFunction(
            SOME_FUNCTION, {0x04: 1 << 20, 0x34: 0x40, 0x40: 0x01}
        )
        pci = sp.PcieHost(ecam=ECAM_BASE)
        msi = sp.MsiHost(receiver=MSI_BASE)

        with pytest.raises(sp.PcieError, match="MSI-X"):
            play(pci.route_interrupts(SOME_FUNCTION, to=msi), function)


class TestWhenMsixIsNotTheFirstOfAFunctionsCapabilities:
    def test_every_vectors_table_entry_is_still_filled_in(self):
        # A function whose list of capabilities starts at 0x40 with
        # another (identifier 0x01, power management) that points on to
        # MSI-X (identifier 0x11) at 0x50. Its table has two vectors (the
        # size, counted from zero, is in the upper half of the first word)
        # at offset 0x2000 behind BAR0, which is at 0x4000_0000.
        function = FakeFunction(
            SOME_FUNCTION,
            {
                0x04: 1 << 20,  # the status bit that says there is a list
                0x10: 0x4000_0004,
                0x34: 0x40,
                0x40: 0x50 << 8 | 0x01,
                0x50: 1 << 16 | 0x11,
                0x54: 0x2000,
            },
        )
        pci = sp.PcieHost(ecam=ECAM_BASE)
        msi = sp.MsiHost(receiver=MSI_BASE)

        play(pci.route_interrupts(SOME_FUNCTION, to=msi), function)

        # An entry is four words: the address in two halves, the data, and
        # a word whose lowest bit masks the vector. The second vector's
        # entry is 16 bytes after the first's.
        assert [
            function.memory_written[0x4000_2000 + offset]
            for offset in (0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C)
        ] == [MSI_BASE, 0, 0, 0, MSI_BASE, 0, 1, 0]


class TestWhenTheHostSwitchesAFunctionOn:
    # The command register is the lower half of the word at 0x04, and the
    # status register the upper half. This function has bit 10 of the
    # command register set (interrupt pin disabled), and every status bit.
    COMMAND_AND_STATUS = 0x04
    AS_FOUND = 0xFFFF_0400

    def test_the_other_bits_of_its_command_register_are_left_as_they_were(
        self,
    ):
        function = FakeFunction(
            SOME_FUNCTION, {self.COMMAND_AND_STATUS: self.AS_FOUND}
        )
        pci = sp.PcieHost(ecam=ECAM_BASE)

        play(pci.place(SOME_FUNCTION, 0x4000_0000), function)

        # Memory decoding and bus mastering, bits 1 and 2, are added.
        written = function.configuration_written[self.COMMAND_AND_STATUS]
        assert written & 0xFFFF == 0x0406

    def test_no_bit_of_its_status_register_is_cleared(self):
        function = FakeFunction(
            SOME_FUNCTION, {self.COMMAND_AND_STATUS: self.AS_FOUND}
        )
        pci = sp.PcieHost(ecam=ECAM_BASE)

        play(pci.place(SOME_FUNCTION, 0x4000_0000), function)

        # Writing a 1 to a status bit is how a host clears it.
        written = function.configuration_written[self.COMMAND_AND_STATUS]
        assert written >> 16 == 0


class FakeFunction:
    """A function's configuration space, for playing the host against.

    It plays `function`. `registers` is what its configuration space
    holds, by offset: every other register reads as zero, and the base
    address register keeps what is written to it. Writes are kept, those
    to configuration space by offset and the rest by address.
    """

    def __init__(self, function, registers):
        # The configuration window gives each function 4 KiB, by device.
        self.base = ECAM_BASE + (function.device << 15)
        self.registers = dict(registers)
        self.configuration_written = {}
        self.memory_written = {}

    def __call__(self, operation):
        address = operation.operands[0]
        offset = address - self.base
        if operation.kind == "read32":
            return self.registers.get(offset, 0)
        if 0 <= offset < 0x1000:
            self.configuration_written[offset] = operation.operands[1]
            if offset in (0x10, 0x14):
                self.registers[offset] = operation.operands[1]
        else:
            self.memory_written[address] = operation.operands[1]
        return None
