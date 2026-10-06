"""The VCML-backed PCIe endpoint, driven from Python.

Run with the spike's package directory first on PYTHONPATH (see README.md).
A script in the host's CPU slot enumerates the endpoint, enables the NVMe
controller behind it and sends one Identify command. The interrupt for its
completion arrives as an MSI-X message: a four-byte write into host memory.
"""

import struct
import sys

import socpuppet as sp
from socpuppet import _core

MEMORY, MEMORY_SIZE = 0x8000_0000, 0x10_0000
ECAM, ECAM_SIZE = 0x3000_0000, 0x1000_0000
WINDOW, WINDOW_SIZE = 0x4000_0000, 0x1000_0000  # where BARs are placed

# Pages of host memory the script hands to the controller.
SUBMISSIONS, COMPLETIONS, IDENTITY = (
    MEMORY + 0x1000,
    MEMORY + 0x2000,
    MEMORY + 0x3000,
)
# Where vector 0's message is sent. A real host points it at its interrupt
# controller. Here it is a word of memory, so the script can look at it.
MESSAGE_AT, MESSAGE = MEMORY + 0xF000, 0xCAFE_0000

seen: dict[str, object] = {}


def host():
    """What the host's software does, as a script for its CPU slot."""
    # Enumeration. Configuration space of function 00:00.0 is the first
    # 4 KiB of the ECAM window.
    ids = yield sp.read32(ECAM + 0x00)
    seen["vendor"], seen["device"] = ids & 0xFFFF, ids >> 16
    seen["class"] = (yield sp.read32(ECAM + 0x08)) >> 8
    seen["absent"] = yield sp.read32(ECAM + (1 << 15))  # device 1: nobody

    # Size BAR0 (write all ones, read back the mask), then place it.
    yield sp.write32(ECAM + 0x10, 0xFFFF_FFFF)
    low = yield sp.read32(ECAM + 0x10)
    yield sp.write32(ECAM + 0x14, 0xFFFF_FFFF)
    high = yield sp.read32(ECAM + 0x14)
    mask = (high << 32 | low) & ~0xF
    seen["bar0_size"] = mask & -mask
    bus_address = 0x0020_0000
    yield sp.write32(ECAM + 0x10, bus_address)
    yield sp.write32(ECAM + 0x14, 0)
    yield sp.write32(ECAM + 0x04, 0x6)  # memory decoding and bus mastering
    bar0 = WINDOW + bus_address

    # Walk the capability list to MSI-X (identifier 0x11).
    at = (yield sp.read32(ECAM + 0x34)) & 0xFF
    while ((header := (yield sp.read32(ECAM + at))) & 0xFF) != 0x11:
        at = (header >> 8) & 0xFF
    table = bar0 + ((yield sp.read32(ECAM + at + 4)) & ~0x7)
    seen["vectors"] = ((header >> 16) & 0x7FF) + 1
    # Vector 0: address, data, unmasked. Then the enable bit, which is bit
    # 15 of the 16-bit control word in the upper half of the header.
    yield sp.write32(table + 0, MESSAGE_AT)
    yield sp.write32(table + 4, 0)
    yield sp.write32(table + 8, MESSAGE)
    yield sp.write32(table + 12, 0)
    yield sp.write32(ECAM + at, header | 1 << 31)

    # The NVMe controller, through BAR0: admin queues of two entries, then
    # CC.EN with 64-byte commands and 16-byte completions.
    yield sp.write32(bar0 + 0x24, 1 << 16 | 1)
    yield sp.write(bar0 + 0x28, struct.pack("<Q", SUBMISSIONS))
    yield sp.write(bar0 + 0x30, struct.pack("<Q", COMPLETIONS))
    yield sp.write32(bar0 + 0x14, 4 << 20 | 6 << 16 | 1)
    yield sp.wait(sp.us(1))
    seen["ready"] = (yield sp.read32(bar0 + 0x1C)) & 1

    # Identify Controller (opcode 6, CNS 1) into the IDENTITY page, then
    # the admin submission queue's tail doorbell.
    command = bytearray(64)
    struct.pack_into("<BxH", command, 0, 0x06, 0x1234)
    struct.pack_into("<Q", command, 24, IDENTITY)
    struct.pack_into("<I", command, 40, 1)
    yield sp.write(SUBMISSIONS, bytes(command))
    yield sp.write32(bar0 + 0x1000, 1)
    yield sp.wait(sp.us(1))

    completion = yield sp.read(COMPLETIONS, 16)
    seen["command_id"], status = struct.unpack_from("<HH", completion, 12)
    seen["status"] = status >> 1
    seen["message"] = yield sp.read32(MESSAGE_AT)
    identity = yield sp.read(IDENTITY, 4096)
    # NN, the number of namespaces: 32 bits at byte 516.
    (seen["namespaces"],) = struct.unpack_from("<I", identity, 516)


def main() -> int:
    """Build the platform, run the script, and say what it saw."""
    platform = _core.Platform(color_log=False)
    platform.add("host.cpu", "scripted_bus_master", {})
    platform.add(
        "host.bus",
        "router",
        {
            "inputs": 2,
            "outputs": 3,
            "out0.base": MEMORY,
            "out0.size": MEMORY_SIZE,
            "out1.base": ECAM,
            "out1.size": ECAM_SIZE,
            "out2.base": WINDOW,
            "out2.size": WINDOW_SIZE,
        },
    )
    platform.add("host.memory", "memory", {"size": MEMORY_SIZE})
    platform.add("ssd.pcie", "vcml_pcie_endpoint", {"vectors": 2})
    platform.add("ssd.nvme", "behavioral_nvme", {"blocks": 64, "vectors": 2})
    platform.set_script("host.cpu", host)
    for source, sink in [
        ("host.cpu.socket", "host.bus.target"),
        ("host.bus.out0", "host.memory.socket"),
        ("host.bus.out1", "ssd.pcie.ecam"),
        ("host.bus.out2", "ssd.pcie.mmio"),
        ("ssd.pcie.dma", "host.bus.in1"),
        ("ssd.pcie.bar0", "ssd.nvme.bar0"),
        ("ssd.nvme.dma", "ssd.pcie.function_dma"),
        ("ssd.nvme.irq0", "ssd.pcie.irq0"),
        ("ssd.nvme.irq1", "ssd.pcie.irq1"),
    ]:
        platform.bind(source, sink, False)
    platform.elaborate()
    platform.run()

    for name, value in seen.items():
        print(
            f"{name:>13}: {value:#x}"
            if isinstance(value, int)
            else f"{name:>13}: {value}"
        )
    expected = {
        "vendor": 0x1DE5,
        "class": 0x010802,
        "absent": 0xFFFF_FFFF,
        "bar0_size": 0x4000,
        "vectors": 2,
        "ready": 1,
        "command_id": 0x1234,
        "status": 0,
        "message": MESSAGE,
        "namespaces": 1,
    }
    wrong = {k: seen.get(k) for k, v in expected.items() if seen.get(k) != v}
    print("❌ not as expected: " + repr(wrong) if wrong else "✅ as expected")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
