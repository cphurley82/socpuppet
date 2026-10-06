"""🎭 The part of a host's firmware that finds PCIe devices and sets them up.

Before a driver can talk to a device, something has to find the device and
give it a place in the host's address map. On a real system that is the
firmware's or the operating system's PCI code. This stands in for it, as
steps a script hands over to with `yield from`:

    def script():
        pci = sp.PcieHost(ecam=0x3000_0000)
        (drive,) = yield from pci.scan()

The layout of configuration space is written from public descriptions of
it (the register definitions in Zephyr's `drivers/pcie` headers among
them).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from socpuppet.errors import PcieError
from socpuppet.ops import Steps, read32, write32

if TYPE_CHECKING:
    from socpuppet.msi_host import MsiHost

# Offsets in a function's configuration space, and bits in the registers
# there.
_IDS = 0x00
# The command register is the lower half of this word and the status
# register the upper half.
_COMMAND_AND_STATUS = 0x04
_MEMORY_DECODING = 1 << 1
_BUS_MASTERING = 1 << 2
_HAS_CAPABILITIES = 1 << 20
_REVISION_AND_CLASS = 0x08
_BAR0 = 0x10
_FIRST_CAPABILITY = 0x34

# The MSI-X capability: its identifier, the enable bit in its first word,
# and the size of an entry of its table.
_MSIX = 0x11
_MSIX_ENABLE = 1 << 31
_MSIX_ENTRY_SIZE = 16

# What a read of the first register gives when no function is there.
_NOBODY = 0xFFFF_FFFF
# How many devices a bus has room for.
_DEVICES = 32


@dataclass(frozen=True)
class PcieFunction:
    """A function found on the bus: where it is, and what it says it is.

    `class_code` is what kind of device it is, as three bytes: class,
    subclass and programming interface (0x010802 for an NVMe drive).
    """

    bus: int
    device: int
    function: int
    vendor_id: int
    device_id: int
    class_code: int

    def __str__(self) -> str:
        """Its address as PCI tools print it: bus:device.function."""
        return f"{self.bus:02x}:{self.device:02x}.{self.function}"


class PcieHost:
    """🎭 Stand-in for the host's PCI code.

    `ecam` is where the root complex's configuration window is in the
    host's address map.
    """

    def __init__(self, *, ecam: int) -> None:
        self._ecam = ecam

    def scan(self) -> Steps[list[PcieFunction]]:
        """Look in every slot of the first bus, and return what is there.

        🎓 This is enumeration. Nothing tells a host which devices it has.
        It reads the first register of every possible device, and a slot
        with nobody in it reads as all ones.
        """
        found = []
        for device in range(_DEVICES):
            ids = yield read32(self._configuration(0, device, 0, _IDS))
            if ids == _NOBODY:
                continue
            revision_and_class = yield read32(
                self._configuration(0, device, 0, _REVISION_AND_CLASS)
            )
            found.append(
                PcieFunction(
                    bus=0,
                    device=device,
                    function=0,
                    vendor_id=ids & 0xFFFF,
                    device_id=ids >> 16,
                    class_code=revision_and_class >> 8,
                )
            )
        return found

    def place(self, function: PcieFunction, address: int) -> Steps[None]:
        """Put a function's registers at `address`, and switch it on.

        🎓 A function asks for a piece of the host's address map with a
        base address register (BAR), and the host answers by writing an
        address into it. This function's BAR is the first, and 64 bits
        wide, in two registers. Nothing behind it answers until memory
        decoding is switched on in the command register, and the function
        may not start accesses of its own (DMA, interrupts) until it is
        made a bus master there.
        """
        yield write32(self._at(function, _BAR0), address & 0xFFFF_FFFF)
        yield write32(self._at(function, _BAR0 + 4), address >> 32)
        # The address bits below the BAR's size cannot be set, so an
        # address that is not a multiple of the size does not stick.
        now_at = yield from self._where_bar0_is(function)
        if now_at != address:
            raise PcieError(
                f"The registers of the function at {function} cannot "
                f"be placed at {address:#x}: its base address register "
                f"reads back as {now_at:#x}. A function's registers go at a "
                "multiple of its size."
            )
        # The other bits of the command register are left as they are. The
        # upper half of the word is the status register, whose bits clear
        # when a 1 is written to them, so it is written as zeros.
        command = yield read32(self._at(function, _COMMAND_AND_STATUS))
        yield write32(
            self._at(function, _COMMAND_AND_STATUS),
            (command & 0xFFFF) | _MEMORY_DECODING | _BUS_MASTERING,
        )

    def route_interrupts(
        self, function: PcieFunction, *, to: MsiHost
    ) -> Steps[None]:
        """Have every interrupt of a function sent to the host's `to`.

        Call it after `place()`.

        🎓 A PCIe function has no interrupt wire. It has a table (MSI-X)
        with an entry for each of its interrupt vectors, and the host
        writes into an entry the address and the 32 bits of data that the
        function is to write there when the vector fires. What the address
        and the data should be is for whatever takes the messages to say,
        which here is `to`.
        """
        capability = yield from self._find_capability(function, _MSIX)
        if capability is None:
            raise PcieError(
                f"The function at {function} has no MSI-X "
                "capability, so its interrupts cannot be routed this way."
            )
        # The capability's first word holds the table's size, counted from
        # zero, in bits 26 to 16. The next says where the table is: which
        # BAR it is behind (the low three bits, and this host knows only
        # the first) and at what offset.
        control: int = yield read32(self._at(function, capability))
        vectors = ((control >> 16) & 0x7FF) + 1
        table = (yield read32(self._at(function, capability + 4))) & ~0x7
        table += yield from self._where_bar0_is(function)
        for vector in range(vectors):
            entry = table + vector * _MSIX_ENTRY_SIZE
            yield write32(entry, to.address & 0xFFFF_FFFF)
            yield write32(entry + 4, to.address >> 32)
            yield write32(entry + 8, to.data_for(vector))
            # The fourth word's lowest bit masks the vector, and it starts
            # out set.
            yield write32(entry + 12, 0)
        yield write32(self._at(function, capability), _MSIX_ENABLE)

    def _find_capability(
        self, function: PcieFunction, wanted: int
    ) -> Steps[int | None]:
        """Where one of a function's capabilities is, if it has it.

        🎓 Features beyond the basics are capabilities, in a linked list. A
        status bit says there is a list, a register says where its first
        entry is, and each entry starts with its identifier and the offset
        of the next.
        """
        status = yield read32(self._at(function, _COMMAND_AND_STATUS))
        if not status & _HAS_CAPABILITIES:
            return None
        first: int = yield read32(self._at(function, _FIRST_CAPABILITY))
        offset = first & 0xFC
        while offset:
            header: int = yield read32(self._at(function, offset))
            if header & 0xFF == wanted:
                return offset
            offset = (header >> 8) & 0xFC
        return None

    def _where_bar0_is(self, function: PcieFunction) -> Steps[int]:
        low: int = yield read32(self._at(function, _BAR0))
        high: int = yield read32(self._at(function, _BAR0 + 4))
        # The low four bits say what kind of BAR it is, not where.
        return (high << 32 | low) & ~0xF

    def _at(self, function: PcieFunction, offset: int) -> int:
        return self._configuration(
            function.bus, function.device, function.function, offset
        )

    def _configuration(
        self, bus: int, device: int, function: int, offset: int
    ) -> int:
        # The window gives every function 4 KiB, laid out by bus, then
        # device, then function (ECAM, the enhanced configuration access
        # mechanism).
        return self._ecam + (bus << 20 | device << 15 | function << 12) + offset
