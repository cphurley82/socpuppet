#ifndef TESTS_CPP_CONTRACTS_IOMMU_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_IOMMU_CONTRACT_H_

#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <optional>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/models/memory.h"
#include "socpuppet/models/pcie_link.h"
#include "socpuppet/platform/slots.h"
#include "socpuppet/platform/transport.h"
#include "tests/cpp/support/bus_driver.h"

// What every IOMMU must do, as the RISC-V IOMMU specification describes
// one, whatever is behind it: the part Linux's riscv-iommu driver and
// socpuppet's Zephyr driver rely on. Devices' accesses come in marked with
// their PCIe requester ID, and the IOMMU's tables and queues are in the
// memory behind it.
//
// To hold an implementation to this contract:
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, IommuContract,
//                                  ::testing::Types<MyIommu>);
// MyIommu must fit the IOMMU slot (see socpuppet/platform/slots.h).
template <socpuppet::IommuSlot IommuType>
class IommuContract : public ::testing::Test {
 protected:
  // The memory behind the IOMMU, from address 0.
  static constexpr std::size_t kMemorySize = 0x10'0000;
  // Where the tests have a device write, in the tests where it does not
  // matter.
  static constexpr std::uint64_t kSomewhere = 0x8'0000;
  // The device the tests' accesses are from: bus 2, device 3, function 1.
  static constexpr std::uint16_t kDevice = 0x0219;

  // The registers the tests use, by their offsets.
  static constexpr std::uint64_t kCapabilities = 0x00;
  static constexpr std::uint64_t kDdtp = 0x10;

  // ddtp: where the device directory's root table is, and what the
  // directory is. Three levels is what Linux asks for.
  static constexpr std::uint64_t kThreeLevels = 4;
  static constexpr std::uint64_t Ddtp(std::uint64_t mode, std::uint64_t root) {
    return ((root >> 12) << 10) | mode;
  }
  static constexpr std::uint64_t ModeOf(std::uint64_t ddtp) {
    return ddtp & 0xF;
  }

  // The tables, each a page of the memory behind the IOMMU: the device
  // directory's three, then the device's Sv39 page tables, from the root.
  static constexpr std::uint64_t kDirectory = 0x1'0000;
  static constexpr std::uint64_t kDirectoryMiddle = 0x1'1000;
  static constexpr std::uint64_t kDirectoryLeaf = 0x1'2000;
  static constexpr std::uint64_t kPageTable = 0x2'0000;
  static constexpr std::uint64_t kPageTableMiddle = 0x2'1000;
  static constexpr std::uint64_t kPageTableLeaf = 0x2'2000;

  // The V bit of a directory entry, a device context's tc, and a page-table
  // entry; and what a page a device may read and write has set besides, as
  // Linux sets them: R, W, U, A and D.
  static constexpr std::uint64_t kV = 1;
  static constexpr std::uint64_t kReadWrite =
      kV | (1U << 1) | (1U << 2) | (1U << 4) | (1U << 6) | (1U << 7);

  // How big an entry of a directory or a page table is, and a device
  // context.
  static constexpr std::uint64_t kEntrySize = 8;
  static constexpr std::uint64_t kContextSize = 32;

  // An entry of a directory or a page table that names the page at
  // `address`.
  static constexpr std::uint64_t EntryFor(std::uint64_t address,
                                          std::uint64_t flags) {
    return ((address >> 12) << 10) | flags;
  }

  // Puts in memory a three-level directory in which kDevice's context has a
  // first stage of Sv39, with its root table at kPageTable. Its ID indexes
  // the directory as bits 23:16, 15:7 and 6:0, and its 32-byte context has
  // tc first and fsc fourth.
  void PlantTheDevicesContext() {
    constexpr std::uint64_t kSv39 = std::uint64_t{8} << 60;
    Plant64(kDirectory + (kEntrySize * ((kDevice >> 16) & 0xFF)),
            EntryFor(kDirectoryMiddle, kV));
    Plant64(kDirectoryMiddle + (kEntrySize * ((kDevice >> 7) & 0x1FF)),
            EntryFor(kDirectoryLeaf, kV));
    const std::uint64_t context =
        kDirectoryLeaf + (kContextSize * (kDevice & 0x7F));
    Plant64(context, kV);
    Plant64(context + 24, kSv39 | (kPageTable >> 12));
  }

  // Puts in kDevice's page tables a 4 KiB page at `page` for the address
  // `iova`, with `flags`.
  void PlantPage(std::uint64_t iova, std::uint64_t page, std::uint64_t flags) {
    Plant64(kPageTable + (kEntrySize * ((iova >> 30) & 0x1FF)),
            EntryFor(kPageTableMiddle, kV));
    Plant64(kPageTableMiddle + (kEntrySize * ((iova >> 21) & 0x1FF)),
            EntryFor(kPageTableLeaf, kV));
    Plant64(kPageTableLeaf + (kEntrySize * ((iova >> 12) & 0x1FF)),
            EntryFor(page, flags));
  }

  void Plant64(std::uint64_t address, std::uint64_t value) {
    DebugWrite(memory_, address, socpuppet::LittleEndianBytes(value));
  }

  // What firmware does to have the IOMMU look devices up in the directory
  // PlantTheDevicesContext made.
  static void UseTheDirectory(BusDriver& firmware) {
    WriteDdtp(firmware, Ddtp(kThreeLevels, kDirectory));
  }

  // What a driver does to write ddtp: waits until the IOMMU has finished
  // with the last write, which ddtp.busy says it has not.
  static void WriteDdtp(BusDriver& firmware, std::uint64_t value) {
    constexpr std::uint64_t kBusy = 1U << 4;
    while ((firmware.Read64(kDdtp) & kBusy) != 0) {
      firmware.WaitFor(sc_core::sc_time{1, sc_core::SC_NS});
    }
    firmware.Write64(kDdtp, value);
  }

  IommuContract() {
    iommu_.initiator.bind(memory_.socket);
    iommu_.irq.bind(line_);
  }

  // Runs `firmware` on the IOMMU's registers and then `device` on its
  // traffic, each in a simulation thread, to completion.
  void Run(const std::function<void(BusDriver&)>& firmware,
           const std::function<void(BusDriver&)>& device) {
    BusDriver firmware_driver{"firmware", firmware};
    BusDriver device_driver{"device", [&](BusDriver& bus) {
                              bus.WaitFor(DeviceStartsAt());
                              device(bus);
                            }};
    firmware_driver.socket.bind(iommu_.socket);
    device_driver.socket.bind(iommu_.target);
    sc_core::sc_start();
  }

  // When the device starts, in the tests where it does: after firmware has
  // set the IOMMU up, which takes it no time.
  static sc_core::sc_time DeviceStartsAt() { return {10, sc_core::SC_NS}; }

  // A device's 32-bit write, marked with its requester ID as a PCIe link
  // would have it.
  static tlm::tlm_response_status DeviceWrite(BusDriver& device,
                                              std::uint64_t address,
                                              std::uint32_t value) {
    std::array data = socpuppet::LittleEndianBytes(value);
    tlm::tlm_generic_payload transaction;
    socpuppet::SetUpAccess(transaction, tlm::TLM_WRITE_COMMAND, address, data);
    const socpuppet::AsFromRequester from_the_device{transaction, kDevice};
    sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
    device.socket->b_transport(transaction, delay);
    return transaction.get_response_status();
  }

  // The same write, from a device that does not say who it is.
  static tlm::tlm_response_status UnmarkedWrite(BusDriver& device,
                                                std::uint64_t address,
                                                std::uint32_t value) {
    return device.Write32(address, value);
  }

  // What the memory behind the IOMMU holds at `address`.
  std::uint32_t InMemory(std::uint64_t address) {
    std::array<std::uint8_t, 4> bytes{};
    DebugRead(memory_, address, bytes);
    return socpuppet::LoadLittleEndian<std::uint32_t>(bytes);
  }

  IommuType iommu_{"iommu"};
  socpuppet::Memory memory_{"memory", kMemorySize};
  sc_core::sc_signal<bool> line_{"line"};
};

TYPED_TEST_SUITE_P(IommuContract);

TYPED_TEST_P(IommuContract, OutOfResetADevicesWriteIsRefusedAndLandsNowhere) {
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  this->Run([](BusDriver&) {},
            [&](BusDriver& device) {
              response = this->DeviceWrite(device, this->kSomewhere, 0x1234);
            });

  EXPECT_EQ(response, tlm::TLM_GENERIC_ERROR_RESPONSE);
  EXPECT_EQ(this->InMemory(this->kSomewhere), 0U);
}

TYPED_TEST_P(IommuContract,
             ADevicesWriteLandsWhereItsPageTablesMapTheAddressItWroteTo) {
  // An address with a different index at each level of the page tables.
  constexpr std::uint64_t kIova = 0x2A'C1E3'3234;
  constexpr std::uint64_t kPage = 0x7'5000;
  this->PlantTheDevicesContext();
  this->PlantPage(kIova, kPage, this->kReadWrite);
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  this->Run(this->UseTheDirectory, [&](BusDriver& device) {
    response = this->DeviceWrite(device, kIova, 0x1234);
  });

  EXPECT_EQ(response, tlm::TLM_OK_RESPONSE);
  EXPECT_EQ(this->InMemory(kPage + (kIova & 0xFFF)), 0x1234U);
}

// There is no device directory entry to look an access up by if it does
// not say which device sent it.
TYPED_TEST_P(IommuContract, AnAccessThatDoesNotSayWhoSentItIsRefused) {
  constexpr std::uint64_t kIova = 0x2A'C1E3'3234;
  constexpr std::uint64_t kPage = 0x7'5000;
  this->PlantTheDevicesContext();
  this->PlantPage(kIova, kPage, this->kReadWrite);
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  this->Run(this->UseTheDirectory, [&](BusDriver& device) {
    response = this->UnmarkedWrite(device, kIova, 0x1234);
  });

  EXPECT_EQ(response, tlm::TLM_GENERIC_ERROR_RESPONSE);
  EXPECT_EQ(this->InMemory(kPage + (kIova & 0xFFF)), 0U);
}

// The mode keeps only values it can hold: Linux asks for three levels and,
// if it reads back anything else, asks for fewer.
TYPED_TEST_P(IommuContract, ADirectoryModeTheSpecReservesDoesNotReadBack) {
  constexpr std::uint64_t kReservedMode = 5;
  std::uint64_t ddtp = 0;
  this->Run(
      [&](BusDriver& firmware) {
        this->WriteDdtp(firmware, this->Ddtp(kReservedMode, this->kDirectory));
        ddtp = firmware.Read64(this->kDdtp);
      },
      [](BusDriver&) {});

  EXPECT_NE(this->ModeOf(ddtp), kReservedMode);
}

// What the drivers read first: which version of the specification, which
// page tables, how it interrupts and how big a device context is.
TYPED_TEST_P(
    IommuContract,
    ItsCapabilitiesAreVersion1WithSv39WiredInterruptsAndBaseFormatContexts) {
  std::uint64_t capabilities = 0;
  this->Run(
      [&](BusDriver& firmware) {
        capabilities = firmware.Read64(this->kCapabilities);
      },
      [](BusDriver&) {});

  // VERSION, bits 7:0, is 1.0 as major and minor nibbles.
  EXPECT_EQ(capabilities & 0xFF, 0x10U);
  // Sv39, bit 9.
  EXPECT_TRUE(capabilities & (1U << 9));
  // IGS, bits 29:28: wired interrupts alone, 1.
  EXPECT_EQ((capabilities >> 28) & 0x3, 1U);
  // MSI_FLAT, bit 22, clear: contexts are the 32-byte base format.
  EXPECT_FALSE(capabilities & (1U << 22));
}

REGISTER_TYPED_TEST_SUITE_P(
    IommuContract, OutOfResetADevicesWriteIsRefusedAndLandsNowhere,
    ADevicesWriteLandsWhereItsPageTablesMapTheAddressItWroteTo,
    AnAccessThatDoesNotSayWhoSentItIsRefused,
    ADirectoryModeTheSpecReservesDoesNotReadBack,
    ItsCapabilitiesAreVersion1WithSv39WiredInterruptsAndBaseFormatContexts);

#endif  // TESTS_CPP_CONTRACTS_IOMMU_CONTRACT_H_
