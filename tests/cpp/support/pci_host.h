#ifndef TESTS_CPP_SUPPORT_PCI_HOST_H_
#define TESTS_CPP_SUPPORT_PCI_HOST_H_

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>

#include <systemc>
#include <tlm>

#include "tests/cpp/contracts/bus_driver.h"

// Where a function is on a PCI bus: its bus, device and function numbers.
struct PciAddress {
  std::uint8_t bus = 0;
  std::uint8_t device = 0;
  std::uint8_t function = 0;
};

// What a read or write came back with.
struct PciAccess {
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  std::uint32_t value = 0;
};

// A small PCI host for tests: the part of a driver that finds a device and
// sets it up, through the root complex's two windows. It runs inside a
// BusDriver's thread.
//
// The layout of configuration space is written from public sources (the
// register definitions in Zephyr's include/zephyr/drivers/pcie/pcie.h and
// msi.h), and none of it is shared with the code under test.
class PciHost {
 public:
  // `ecam` is where the configuration window is on the host's bus.
  PciHost(BusDriver& bus, std::uint64_t ecam) : bus_(bus), ecam_(ecam) {}

  // Reads 32 bits of a function's configuration space. The window gives
  // every function 4 KiB, laid out by bus, then device, then function
  // (ECAM, the enhanced configuration access mechanism).
  PciAccess ReadConfig(PciAddress function, std::uint64_t offset) {
    return Read(Config(function, offset));
  }

  // Who made a function and which of their devices it is: the first word
  // of configuration space, vendor in the low half.
  struct Identity {
    std::uint16_t vendor = 0;
    std::uint16_t device = 0;
  };
  Identity IdsOf(PciAddress function) {
    const std::uint32_t ids = ReadConfig(function, 0x00).value;
    return {.vendor = static_cast<std::uint16_t>(ids),
            .device = static_cast<std::uint16_t>(ids >> 16)};
  }

  // What kind of device it is: the three bytes above the revision, in the
  // word at 0x08.
  std::uint32_t ClassCodeOf(PciAddress function) {
    return ReadConfig(function, 0x08).value >> 8;
  }

  PciAccess WriteConfig(PciAddress function, std::uint64_t offset,
                        std::uint32_t value) {
    return Write(Config(function, offset), value);
  }

  // The first base address register (BAR0), as a host uses it. A BAR is
  // how a function asks for a piece of the host's address map for its
  // registers, and how the host says where it has put them. This one is
  // 64 bits wide, in two registers.

  // What kind of BAR it is: the low four bits, which the host cannot
  // change. 0x4 there means a 64-bit memory BAR.
  std::uint32_t KindOfBar0(PciAddress function) {
    return ReadConfig(function, kBar0).value & 0xF;
  }

  // How much address space the function wants. The host finds out by
  // writing all ones and reading back: the bits that stay zero are the
  // ones the function does not decode, which gives the size.
  std::uint64_t SizeOfBar0(PciAddress function) {
    WriteConfig(function, kBar0, 0xFFFF'FFFF);
    WriteConfig(function, kBar0 + 4, 0xFFFF'FFFF);
    return ~(Bar0(function) & ~std::uint64_t{0xF}) + 1;
  }

  // Says where on the host's bus the function's registers are to be.
  void PlaceBar0(PciAddress function, std::uint64_t address) {
    WriteConfig(function, kBar0, static_cast<std::uint32_t>(address));
    WriteConfig(function, kBar0 + 4, static_cast<std::uint32_t>(address >> 32));
  }

  // Where the function says they are, without the low bits that say what
  // kind of BAR it is.
  std::uint64_t PlaceOfBar0(PciAddress function) {
    return Bar0(function) & ~std::uint64_t{0xF};
  }

  // Sets bits in the command register. Nothing behind a BAR answers until
  // memory decoding is switched on there.
  static constexpr std::uint32_t kMemoryDecoding = 1U << 1;
  // And the function may not start accesses of its own (DMA, interrupt
  // messages) until the host lets it be a bus master.
  static constexpr std::uint32_t kBusMastering = 1U << 2;
  void Command(PciAddress function, std::uint32_t bits) {
    WriteConfig(function, kCommand,
                (ReadConfig(function, kCommand).value & 0xFFFF) | bits);
  }

  // MSI-X: how a PCIe function interrupts. There is no wire. The function
  // has a table with an entry for each of its interrupt vectors, and the
  // host writes into an entry the address and the 32 bits of data that the
  // function is to write there when that vector fires. The write is the
  // interrupt: whatever the host has at that address turns it into one.

  // Where a function's MSI-X registers are on the host's bus.
  struct Msix {
    // The capability, in configuration space.
    std::uint64_t capability = 0;
    std::uint32_t vectors = 0;
    // The table and the pending bits, which are behind BAR0.
    std::uint64_t table = 0;
    std::uint64_t pending = 0;
  };

  // Finds the function's MSI-X registers by walking its list of
  // capabilities, which starts at the offset the register at 0x34 gives.
  // Each capability starts with its identifier and the offset of the next.
  // BAR0 must have been placed already.
  std::optional<Msix> FindMsix(PciAddress function) {
    if ((ReadConfig(function, kCommand).value & kHasCapabilities) == 0) {
      return std::nullopt;
    }
    std::uint64_t capability = ReadConfig(function, kCapabilities).value & 0xFC;
    while (capability != 0) {
      const std::uint32_t header = ReadConfig(function, capability).value;
      if ((header & 0xFF) == kMsixCapability) {
        // The table's size, counted from zero, is in the low 11 bits of
        // the upper half. The two registers after it say which BAR the
        // table and the pending bits are behind (the low three bits; here
        // it has to be BAR0) and at what offset.
        const std::uint64_t bar0 = PlaceOfBar0(function);
        return Msix{
            .capability = capability,
            .vectors = ((header >> 16) & 0x7FF) + 1,
            .table = bar0 + (ReadConfig(function, capability + 4).value & ~7U),
            .pending =
                bar0 + (ReadConfig(function, capability + 8).value & ~7U)};
      }
      capability = (header >> 8) & 0xFC;
    }
    return std::nullopt;
  }

  // Fills in a vector's table entry: the address, in two halves, and the
  // data. The fourth word of an entry holds its mask bit, which this
  // leaves alone.
  void SetUpVector(const Msix& msix, std::uint32_t vector,
                   std::uint64_t address, std::uint32_t data) {
    const std::uint64_t entry = msix.table + (vector * kMsixEntrySize);
    Write(entry, static_cast<std::uint32_t>(address));
    Write(entry + 4, static_cast<std::uint32_t>(address >> 32));
    Write(entry + 8, data);
  }

  // A masked vector sends nothing. Every vector starts out masked.
  void MaskVector(const Msix& msix, std::uint32_t vector, bool masked) {
    Write(msix.table + (vector * kMsixEntrySize) + 12, masked ? 1 : 0);
  }

  // Whether a vector fired while it could not be sent, and is waiting.
  bool IsPending(const Msix& msix, std::uint32_t vector) {
    const std::uint64_t word = msix.pending + (std::uint64_t{vector / 32} * 4);
    return ((Read(word).value >> (vector % 32)) & 1) != 0;
  }

  // Writes the MSI-X capability's control register, which is the upper
  // half of its first word: these bits are set and the others cleared.
  static constexpr std::uint32_t kMsixEnable = 1U << 31;
  static constexpr std::uint32_t kMsixMaskEveryVector = 1U << 30;
  void MsixControl(PciAddress function, const Msix& msix, std::uint32_t bits) {
    WriteConfig(function, msix.capability, bits);
  }

  void WaitFor(const sc_core::sc_time& duration) { bus_.WaitFor(duration); }

  // 32-bit accesses to the host's bus, for what is behind a BAR.
  PciAccess Read(std::uint64_t address) {
    std::array<std::uint8_t, 4> bytes{};
    PciAccess access;
    access.response = bus_.Read(address, bytes);
    for (std::size_t index = 0; index < bytes.size(); ++index) {
      access.value |= std::uint32_t{bytes[index]} << (8 * index);
    }
    return access;
  }

  PciAccess Write(std::uint64_t address, std::uint32_t value) {
    std::array<std::uint8_t, 4> bytes{};
    for (std::size_t index = 0; index < bytes.size(); ++index) {
      bytes[index] = static_cast<std::uint8_t>(value >> (8 * index));
    }
    return {.response = bus_.Write(address, bytes), .value = value};
  }

 private:
  // Offsets in configuration space.
  static constexpr std::uint64_t kCommand = 0x04;
  // The status register is the upper half of the word the command
  // register is the lower half of, and this bit of it says the function
  // has a list of capabilities.
  static constexpr std::uint32_t kHasCapabilities = 1U << 20;
  static constexpr std::uint64_t kBar0 = 0x10;
  static constexpr std::uint64_t kCapabilities = 0x34;
  static constexpr std::uint32_t kMsixCapability = 0x11;
  static constexpr std::uint64_t kMsixEntrySize = 16;

  std::uint64_t Bar0(PciAddress function) {
    return ReadConfig(function, kBar0).value |
           std::uint64_t{ReadConfig(function, kBar0 + 4).value} << 32;
  }

  std::uint64_t Config(PciAddress function, std::uint64_t offset) const {
    return ecam_ + (std::uint64_t{function.bus} << 20) +
           (std::uint64_t{function.device} << 15) +
           (std::uint64_t{function.function} << 12) + offset;
  }

  BusDriver& bus_;
  std::uint64_t ecam_;
};

#endif  // TESTS_CPP_SUPPORT_PCI_HOST_H_
