#ifndef TESTS_CPP_CONTRACTS_IOMMU_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_IOMMU_CONTRACT_H_

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <initializer_list>
#include <optional>
#include <span>

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
  static constexpr std::uint64_t kFctl = 0x08;
  static constexpr std::uint64_t kDdtp = 0x10;
  static constexpr std::uint64_t kCqb = 0x18;
  static constexpr std::uint64_t kCqh = 0x20;
  static constexpr std::uint64_t kCqt = 0x24;
  static constexpr std::uint64_t kFqb = 0x28;
  static constexpr std::uint64_t kFqh = 0x30;
  static constexpr std::uint64_t kFqt = 0x34;
  static constexpr std::uint64_t kCqcsr = 0x48;
  static constexpr std::uint64_t kFqcsr = 0x4C;
  // Which queues want attention, a bit each, cleared by writing it: the
  // command queue's is bit 0 and the fault queue's bit 1.
  static constexpr std::uint64_t kIpsr = 0x54;
  static constexpr std::uint32_t kCommandQueuePending = 1U << 0U;
  static constexpr std::uint32_t kFaultQueuePending = 1U << 1U;
  // Which interrupt vector each cause is on, four bits each: the command
  // queue's in bits 3:0, the fault queue's in 7:4, then the performance
  // monitor's and the page-request queue's.
  static constexpr std::uint64_t kIcvec = 0x2F8;

  // A queue's control and status register, the same for each queue: its
  // enable and interrupt enable, which software sets, and its on and busy,
  // which the IOMMU does. A memory fault, bit 8, software clears by
  // writing it.
  static constexpr std::uint32_t kEnable = 1U << 0U;
  static constexpr std::uint32_t kInterruptEnable = 1U << 1U;
  static constexpr std::uint32_t kMemoryFault = 1U << 8U;
  static constexpr std::uint32_t kOn = 1U << 16U;
  static constexpr std::uint32_t kBusy = 1U << 17U;
  // And what goes wrong that each queue reports there: a command the IOMMU
  // does not have, and a record with no room in the fault queue.
  static constexpr std::uint32_t kCommandIllegal = 1U << 10U;
  static constexpr std::uint32_t kOverflow = 1U << 9U;

  // ddtp: where the device directory's root table is, and what the
  // directory is. Three levels is what Linux asks for.
  static constexpr std::uint64_t kThreeLevels = 4;
  static constexpr std::uint64_t Ddtp(std::uint64_t mode, std::uint64_t root) {
    return ((root >> 12U) << 10U) | mode;
  }
  static constexpr std::uint64_t ModeOf(std::uint64_t ddtp) {
    return ddtp & 0xFU;
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
  static constexpr std::uint64_t kNotValid = 0;
  static constexpr std::uint64_t kReadWrite =
      kV | (1U << 1U) | (1U << 2U) | (1U << 4U) | (1U << 6U) | (1U << 7U);

  // How big an entry of a directory or a page table is, and a device
  // context.
  static constexpr std::uint64_t kEntrySize = 8;
  static constexpr std::uint64_t kContextSize = 32;

  // An entry of a directory or a page table that names the page at
  // `address`.
  static constexpr std::uint64_t EntryFor(std::uint64_t address,
                                          std::uint64_t flags) {
    return ((address >> 12U) << 10U) | flags;
  }

  // Puts in memory a three-level directory in which kDevice's context has a
  // first stage of Sv39, with its root table at kPageTable. Its ID indexes
  // the directory as bits 23:16, 15:7 and 6:0, and its 32-byte context has
  // tc first and fsc fourth.
  void PlantTheDevicesContext() {
    constexpr std::uint64_t kSv39 = std::uint64_t{8} << 60U;
    Plant64(
        kDirectory + (kEntrySize * ((std::uint32_t{kDevice} >> 16U) & 0xFFU)),
        EntryFor(kDirectoryMiddle, kV));
    Plant64(kDirectoryMiddle +
                (kEntrySize * ((std::uint32_t{kDevice} >> 7U) & 0x1FFU)),
            EntryFor(kDirectoryLeaf, kV));
    const std::uint64_t context =
        kDirectoryLeaf + (kContextSize * (kDevice & 0x7FU));
    Plant64(context, kV);
    Plant64(context + 24, kSv39 | (kPageTable >> 12U));
  }

  // The address the tests' devices use, with a different index at each
  // level of the page tables, and the page the tests map it to.
  static constexpr std::uint64_t kIova = 0x2A'C1E3'3234;
  static constexpr std::uint64_t kPage = 0x7'5000;
  // The last word of kIova's page, the page after it, and a page for that
  // one that is not the page after kPage, so that a transfer that crosses
  // cannot land right by luck.
  static constexpr std::uint64_t kEndOfThePage = kIova | 0xFFCU;
  static constexpr std::uint64_t kNextIova = (kIova | 0xFFFU) + 1;
  static constexpr std::uint64_t kNextPage = 0x7'9000;

  // Puts in kDevice's page tables a 4 KiB page at `page` for the address
  // `iova`, with `flags`.
  void PlantPage(std::uint64_t iova, std::uint64_t page, std::uint64_t flags) {
    Plant64(kPageTable + (kEntrySize * ((iova >> 30U) & 0x1FFU)),
            EntryFor(kPageTableMiddle, kV));
    Plant64(kPageTableMiddle + (kEntrySize * ((iova >> 21U) & 0x1FFU)),
            EntryFor(kPageTableLeaf, kV));
    Plant64(kPageTableLeaf + (kEntrySize * ((iova >> 12U) & 0x1FFU)),
            EntryFor(page, flags));
  }

  // Puts in memory kDevice's context, and an entry for kIova's page that is
  // not valid, so that any access to it is a page fault.
  void PlantAPageThatIsNotValid() {
    PlantTheDevicesContext();
    PlantPage(kIova, kPage, kNotValid);
  }

  void Plant64(std::uint64_t address, std::uint64_t value) {
    DebugWrite(memory_, address, socpuppet::LittleEndianBytes(value));
  }

  // What firmware does to have the IOMMU look devices up in the directory
  // PlantTheDevicesContext made.
  static void UseTheDirectory(BusDriver& firmware) {
    WriteDdtp(firmware, Ddtp(kThreeLevels, kDirectory));
  }

  // Where the tests put the command queue, and how big: 2^(kQueueLog2 + 1)
  // entries of 16 bytes.
  static constexpr std::uint64_t kCommandQueue = 0x3'0000;
  static constexpr std::uint64_t kQueueLog2 = 3;

  // A queue's base register: the page the queue starts at in bits 53:10,
  // and LOG2SZ, one less than the log of its entries, in bits 4:0.
  static constexpr std::uint64_t QueueBase(std::uint64_t address,
                                           std::uint64_t log2_size) {
    return ((address >> 12U) << 10U) | log2_size;
  }

  // Commands: an opcode in bits 6:0 of the first doubleword and a function
  // in bits 9:7. What Linux sends: IOTINVAL.VMA, which says page tables
  // changed; IODIR.INVAL_DDT, which says the directory did; and IOFENCE.C,
  // which waits for the commands before it, and with AV, bit 10, then
  // writes its DATA, bits 63:32, to the address its second doubleword
  // holds, shifted right by two.
  struct Command {
    std::uint64_t first;
    std::uint64_t second = 0;
  };
  static constexpr Command kInvalidatePageTables{.first = 1};
  static constexpr Command kInvalidateTheDirectory{.first = 3};
  static constexpr Command kFence{.first = 2};
  static constexpr Command FenceThatWrites(std::uint32_t data,
                                           std::uint64_t address) {
    constexpr std::uint64_t kAv = 1U << 10U;
    return {.first = kFence.first | kAv | (std::uint64_t{data} << 32U),
            .second = address >> 2U};
  }
  // And one this IOMMU does not have: ATS.INVAL, for a device that caches
  // translations, which needs ATS.
  static constexpr Command kAtsInvalidate{.first = 4};

  // Puts `commands` in the command queue from its first entry.
  void PlantCommands(std::initializer_list<Command> commands) {
    std::uint64_t at = kCommandQueue;
    for (const Command& command : commands) {
      Plant64(at, command.first);
      Plant64(at + 8, command.second);
      at += 16;
    }
  }

  // What firmware does to start the command queue, as Linux does: says
  // where it is, empties it and turns it on.
  static void StartTheCommandQueue(BusDriver& firmware) {
    firmware.Write64(kCqb, QueueBase(kCommandQueue, kQueueLog2));
    firmware.Write32(kCqt, 0);
    firmware.Write32(kCqcsr, kEnable | kInterruptEnable | kMemoryFault);
    WhenNotBusy(firmware, kCqcsr);
  }

  // Where the tests put the fault queue, of 2^(kQueueLog2 + 1) records of
  // 32 bytes.
  static constexpr std::uint64_t kFaultQueue = 0x3'8000;

  // What firmware does to start the fault queue, as Linux does: says where
  // it is, empties it and turns it on.
  static void StartTheFaultQueue(BusDriver& firmware) {
    firmware.Write64(kFqb, QueueBase(kFaultQueue, kQueueLog2));
    firmware.Write32(kFqh, 0);
    firmware.Write32(kFqcsr, kEnable | kInterruptEnable | kMemoryFault);
    WhenNotBusy(firmware, kFqcsr);
  }

  // A fault record as the IOMMU writes one: its header, with the cause in
  // bits 11:0, the transaction's type in 39:34 and the device in 63:40;
  // and the address the device used.
  struct FaultRecord {
    std::uint64_t header;
    std::uint64_t address;

    bool operator==(const FaultRecord&) const = default;
  };
  static constexpr FaultRecord Record(std::uint64_t cause, std::uint64_t type,
                                      std::uint64_t address) {
    return {.header = cause | (type << 34U) | (std::uint64_t{kDevice} << 40U),
            .address = address};
  }
  // The record at entry `index` of the fault queue.
  FaultRecord RecordAt(std::uint64_t index) {
    const std::uint64_t at = kFaultQueue + (index * kRecordSize);
    return {.header = InMemory64(at), .address = InMemory64(at + 16)};
  }
  static constexpr std::uint64_t kRecordSize = 32;

  // Fills the fault queue, as far as the IOMMU can tell: with the tail at 0
  // and the head, where software has read up to, at 1, one record more
  // would bring the tail to the head.
  static void FillTheFaultQueue(BusDriver& firmware) {
    firmware.Write32(kFqh, 1);
  }

  // How long a test polls a register for what it waits on: far longer than
  // the IOMMU takes over anything a test asks of it, which is no time at
  // all for its own part.
  static constexpr int kPolls = 1000;
  static sc_core::sc_time BetweenPolls() { return {1, sc_core::SC_NS}; }

  // Where the command queue's head is once it has come to `tail`, or when
  // the test stops polling, as a driver polls it.
  static std::uint32_t HeadOnceAt(BusDriver& firmware, std::uint32_t tail) {
    std::uint32_t head = firmware.Read32(kCqh);
    for (int polls = 0; head != tail && polls < kPolls; ++polls) {
      firmware.WaitFor(BetweenPolls());
      head = firmware.Read32(kCqh);
    }
    return head;
  }

  // What the 32-bit register at `offset` reads once any of `bits` is set, or
  // when the test stops polling.
  static std::uint32_t OnceSet(BusDriver& firmware, std::uint64_t offset,
                               std::uint32_t bits) {
    std::uint32_t value = firmware.Read32(offset);
    for (int polls = 0; (value & bits) == 0 && polls < kPolls; ++polls) {
      firmware.WaitFor(BetweenPolls());
      value = firmware.Read32(offset);
    }
    return value;
  }

  // What a queue's control and status register reads once it says the
  // queue is not busy, as a driver waits for it.
  static std::uint32_t WhenNotBusy(BusDriver& firmware, std::uint64_t csr) {
    std::uint32_t value = firmware.Read32(csr);
    while ((value & kBusy) != 0) {
      firmware.WaitFor(sc_core::sc_time{1, sc_core::SC_NS});
      value = firmware.Read32(csr);
    }
    return value;
  }

  // What a driver does to write ddtp: waits until the IOMMU has finished
  // with the last write, which ddtp.busy says it has not.
  static void WriteDdtp(BusDriver& firmware, std::uint64_t value) {
    constexpr std::uint64_t kDdtpBusy = 1U << 4U;
    while ((firmware.Read64(kDdtp) & kDdtpBusy) != 0) {
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

  // Waits, as firmware, until after the device's access, which starts at
  // DeviceStartsAt and takes the IOMMU no time of its own.
  static void WaitForTheDevice(BusDriver& firmware) {
    firmware.WaitFor(2 * DeviceStartsAt());
  }

  // A device's 32-bit write, marked with its requester ID as a PCIe link
  // would have it.
  static tlm::tlm_response_status DeviceWrite(BusDriver& device,
                                              std::uint64_t address,
                                              std::uint32_t value) {
    std::array data = socpuppet::LittleEndianBytes(value);
    return DeviceWriteBytes(device, address, data);
  }

  // A device's 64-bit write, marked the same way.
  static tlm::tlm_response_status DeviceWrite64(BusDriver& device,
                                                std::uint64_t address,
                                                std::uint64_t value) {
    std::array data = socpuppet::LittleEndianBytes(value);
    return DeviceWriteBytes(device, address, data);
  }

  // A device's write of `data`, however long, marked the same way.
  static tlm::tlm_response_status DeviceWriteBytes(
      BusDriver& device, std::uint64_t address, std::span<std::uint8_t> data) {
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
  std::uint64_t InMemory64(std::uint64_t address) {
    std::array<std::uint8_t, 8> bytes{};
    DebugRead(memory_, address, bytes);
    return socpuppet::LoadLittleEndian<std::uint64_t>(bytes);
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
  this->PlantTheDevicesContext();
  this->PlantPage(this->kIova, this->kPage, this->kReadWrite);
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  this->Run(this->UseTheDirectory, [&](BusDriver& device) {
    response = this->DeviceWrite(device, this->kIova, 0x1234);
  });

  EXPECT_EQ(response, tlm::TLM_OK_RESPONSE);
  EXPECT_EQ(this->InMemory(this->kPage + (this->kIova & 0xFFFU)), 0x1234U);
}

// A transfer that crosses a page is translated a page at a time, as a real
// IOMMU sees it: a PCIe request stops at 4 KiB, so each page goes where its
// own entry says, not where the first page's entry plus an offset would.
TYPED_TEST_P(IommuContract, AWriteThatCrossesAPageLandsWhereEachPageIsMapped) {
  this->PlantTheDevicesContext();
  this->PlantPage(this->kIova, this->kPage, this->kReadWrite);
  this->PlantPage(this->kNextIova, this->kNextPage, this->kReadWrite);
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  this->Run(this->UseTheDirectory, [&](BusDriver& device) {
    response =
        this->DeviceWrite64(device, this->kEndOfThePage, 0x5678'0000'1234);
  });

  EXPECT_EQ(response, tlm::TLM_OK_RESPONSE);
  EXPECT_EQ(this->InMemory(this->kPage + (this->kEndOfThePage & 0xFFFU)),
            0x1234U);
  EXPECT_EQ(this->InMemory(this->kNextPage), 0x5678U);
}

// And one that crosses into a page it may not use stops at that page, the
// pages before it done, as the requests before a refused one are: the
// fault record, a write page fault (cause 15) of an untranslated write
// (type 3), is for the page that was refused.
TYPED_TEST_P(IommuContract,
             AWriteThatCrossesIntoAPageThatIsNotValidStopsThere) {
  this->PlantTheDevicesContext();
  this->PlantPage(this->kIova, this->kPage, this->kReadWrite);
  this->PlantPage(this->kNextIova, this->kNextPage, this->kNotValid);
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  this->Run(
      [&](BusDriver& firmware) {
        this->StartTheFaultQueue(firmware);
        this->UseTheDirectory(firmware);
      },
      [&](BusDriver& device) {
        response =
            this->DeviceWrite64(device, this->kEndOfThePage, 0x5678'0000'1234);
      });

  EXPECT_EQ(response, tlm::TLM_GENERIC_ERROR_RESPONSE);
  EXPECT_EQ(this->InMemory(this->kPage + (this->kEndOfThePage & 0xFFFU)),
            0x1234U);
  EXPECT_EQ(this->InMemory(this->kNextPage), 0U);
  EXPECT_EQ(this->RecordAt(0), this->Record(15, 3, this->kNextIova));
}

// There is no device directory entry to look an access up by if it does
// not say which device sent it.
TYPED_TEST_P(IommuContract, AnAccessThatDoesNotSayWhoSentItIsRefused) {
  this->PlantTheDevicesContext();
  this->PlantPage(this->kIova, this->kPage, this->kReadWrite);
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  this->Run(this->UseTheDirectory, [&](BusDriver& device) {
    response = this->UnmarkedWrite(device, this->kIova, 0x1234);
  });

  EXPECT_EQ(response, tlm::TLM_GENERIC_ERROR_RESPONSE);
  EXPECT_EQ(this->InMemory(this->kPage + (this->kIova & 0xFFFU)), 0U);
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

// busy, bit 4, is the IOMMU's to say, and drivers wait for it to clear
// before each write: one that software could set would never clear.
TYPED_TEST_P(IommuContract, AWriteToDdtpCannotMakeItBusy) {
  constexpr std::uint64_t kBusyBit = 1U << 4U;
  std::uint64_t ddtp = 0;
  this->Run(
      [&](BusDriver& firmware) {
        firmware.Write64(
            this->kDdtp,
            this->Ddtp(this->kThreeLevels, this->kDirectory) | kBusyBit);
        ddtp = firmware.Read64(this->kDdtp);
      },
      [](BusDriver&) {});

  EXPECT_EQ(ddtp & kBusyBit, 0U);
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
  EXPECT_EQ(capabilities & 0xFFU, 0x10U);
  // Sv39, bit 9.
  EXPECT_TRUE(capabilities & (1U << 9U));
  // IGS, bits 29:28: wired interrupts alone, 1.
  EXPECT_EQ((capabilities >> 28U) & 0x3U, 1U);
  // MSI_FLAT, bit 22, clear: contexts are the 32-byte base format.
  EXPECT_FALSE(capabilities & (1U << 22U));
}

// A queue's base register says where the queue is and how big: LOG2SZ,
// bits 4:0, is one less than the log of its entries. Linux finds out the
// biggest it may ask for by writing all ones there, then asks for no more,
// and checks the register reads back what it wrote.
TYPED_TEST_P(IommuContract, ACommandQueueOfTheSizeItCanHoldReadsBack) {
  constexpr std::uint64_t kLog2SizeField = 0x1F;
  constexpr std::uint64_t kWanted = 9;  // 1,024 entries
  std::uint64_t biggest = 0;
  std::uint64_t cqb = 0;
  std::uint64_t asked = 0;
  this->Run(
      [&](BusDriver& firmware) {
        firmware.Write64(this->kCqb, kLog2SizeField);
        biggest = firmware.Read64(this->kCqb) & kLog2SizeField;
        asked =
            this->QueueBase(this->kCommandQueue, std::min(kWanted, biggest));
        firmware.Write64(this->kCqb, asked);
        cqb = firmware.Read64(this->kCqb);
      },
      [](BusDriver&) {});

  EXPECT_GT(biggest, 0U);
  EXPECT_EQ(cqb, asked);
}

// Linux turns a queue on with its interrupt on and any memory fault
// cleared, waits until the queue is not busy, and then wants it on, not
// busy and with no memory fault. Turned off, it is off.
TYPED_TEST_P(IommuContract, ACommandQueueIsOnWhileItIsEnabled) {
  std::uint32_t enabled = 0;
  std::uint32_t disabled = 0;
  this->Run(
      [&](BusDriver& firmware) {
        firmware.Write32(this->kCqcsr, this->kEnable | this->kInterruptEnable |
                                           this->kMemoryFault);
        enabled = this->WhenNotBusy(firmware, this->kCqcsr);
        firmware.Write32(this->kCqcsr, 0);
        disabled = this->WhenNotBusy(firmware, this->kCqcsr);
      },
      [](BusDriver&) {});

  EXPECT_EQ(enabled & (this->kOn | this->kMemoryFault), this->kOn);
  EXPECT_EQ(disabled & this->kOn, 0U);
}

// Changing cqen from 0 to 1 sets cqh and cqt to 0, the specification says,
// and a driver that turns a queue on again counts on it: Linux writes the
// tail and cannot write the head.
TYPED_TEST_P(IommuContract, EnablingTheCommandQueueEmptiesIt) {
  this->PlantCommands({this->kInvalidatePageTables, this->kFence});
  std::uint32_t head = 0;
  std::uint32_t tail = 0;
  this->Run(
      [&](BusDriver& firmware) {
        this->StartTheCommandQueue(firmware);
        firmware.Write32(this->kCqt, 2);
        this->HeadOnceAt(firmware, 2);
        firmware.Write32(this->kCqcsr, 0);
        this->WhenNotBusy(firmware, this->kCqcsr);
        firmware.Write32(this->kCqcsr, this->kEnable);
        this->WhenNotBusy(firmware, this->kCqcsr);
        head = firmware.Read32(this->kCqh);
        tail = firmware.Read32(this->kCqt);
      },
      [](BusDriver&) {});

  EXPECT_EQ(head, 0U);
  EXPECT_EQ(tail, 0U);
}

// The same for the fault queue, where it is the tail that is the IOMMU's.
TYPED_TEST_P(IommuContract, EnablingTheFaultQueueEmptiesIt) {
  this->PlantAPageThatIsNotValid();
  std::uint32_t head = 0;
  std::uint32_t tail = 0;
  this->Run(
      [&](BusDriver& firmware) {
        this->StartTheFaultQueue(firmware);
        this->UseTheDirectory(firmware);
        this->WaitForTheDevice(firmware);
        firmware.Write32(this->kFqh, 1);
        firmware.Write32(this->kFqcsr, 0);
        this->WhenNotBusy(firmware, this->kFqcsr);
        firmware.Write32(this->kFqcsr, this->kEnable);
        this->WhenNotBusy(firmware, this->kFqcsr);
        head = firmware.Read32(this->kFqh);
        tail = firmware.Read32(this->kFqt);
      },
      [&](BusDriver& device) {
        this->DeviceWrite(device, this->kIova, 0x1234);
      });

  EXPECT_EQ(head, 0U);
  EXPECT_EQ(tail, 0U);
}

// cqt is an index into the queue, and the bits above the queue's size are
// not writable: a tail past the end is the entry it wraps to, so the head
// can always reach it.
TYPED_TEST_P(IommuContract, TheCommandQueuesTailIsOnlyAsWideAsTheQueue) {
  constexpr std::uint32_t kEntries = 1U << (TestFixture::kQueueLog2 + 1);
  std::uint32_t tail = 0;
  this->Run(
      [&](BusDriver& firmware) {
        this->StartTheCommandQueue(firmware);
        firmware.Write32(this->kCqt, kEntries + 1);
        tail = firmware.Read32(this->kCqt);
      },
      [](BusDriver&) {});

  EXPECT_EQ(tail, 1U);
}

TYPED_TEST_P(IommuContract, ACommandQueueThatIsOnRunsItsCommandsToTheTail) {
  this->PlantCommands({this->kInvalidatePageTables,
                       this->kInvalidateTheDirectory, this->kFence});
  std::uint32_t head = 0;
  this->Run(
      [&](BusDriver& firmware) {
        this->StartTheCommandQueue(firmware);
        firmware.Write32(this->kCqt, 3);
        head = this->HeadOnceAt(firmware, 3);
      },
      [](BusDriver&) {});

  EXPECT_EQ(head, 3U);
}

// The fence a driver waits on: with AV, the fence writes its DATA where it
// says once the commands before it are done, and the driver watches that
// word.
TYPED_TEST_P(IommuContract, AFenceThatAsksToBeSeenWritesItsDataWhereItSays) {
  constexpr std::uint32_t kData = 0xC0DE'0001;
  constexpr std::uint64_t kWord = 0x4'0040;
  this->PlantCommands(
      {this->kInvalidatePageTables, this->FenceThatWrites(kData, kWord)});
  this->Run(
      [&](BusDriver& firmware) {
        this->StartTheCommandQueue(firmware);
        firmware.Write32(this->kCqt, 2);
        this->HeadOnceAt(firmware, 2);
      },
      [](BusDriver&) {});

  EXPECT_EQ(this->InMemory(kWord), kData);
}

// A command the IOMMU does not have stops the queue at it, with cmd_ill,
// bit 10 of cqcsr, set for software to see and clear.
TYPED_TEST_P(IommuContract, ACommandItDoesNotHaveStopsTheQueueAtIt) {
  this->PlantCommands(
      {this->kInvalidatePageTables, this->kAtsInvalidate, this->kFence});
  std::uint32_t head = 0;
  std::uint32_t cqcsr = 0;
  this->Run(
      [&](BusDriver& firmware) {
        this->StartTheCommandQueue(firmware);
        firmware.Write32(this->kCqt, 3);
        cqcsr = this->OnceSet(firmware, this->kCqcsr, this->kCommandIllegal);
        head = firmware.Read32(this->kCqh);
      },
      [](BusDriver&) {});

  EXPECT_TRUE(cqcsr & this->kCommandIllegal);
  EXPECT_EQ(head, 1U);
}

// A write to a page whose entry is not valid is a write page fault, cause
// 15, of an untranslated write, type 3; the record goes where the fault
// queue's tail is, and the tail moves past it.
TYPED_TEST_P(IommuContract, ARefusedAccessIsRecordedAtTheFaultQueuesTail) {
  this->PlantAPageThatIsNotValid();
  std::uint32_t tail = 0;
  this->Run(
      [&](BusDriver& firmware) {
        this->StartTheFaultQueue(firmware);
        this->UseTheDirectory(firmware);
        this->WaitForTheDevice(firmware);
        tail = firmware.Read32(this->kFqt);
      },
      [&](BusDriver& device) {
        this->DeviceWrite(device, this->kIova, 0x1234);
      });

  EXPECT_EQ(this->RecordAt(0), this->Record(15, 3, this->kIova));
  EXPECT_EQ(tail, 1U);
}

// A record in the fault queue is for software's attention: IPSR.FIP says
// so, and while the fault queue's interrupt is enabled the line is up,
// until software has cleared FIP.
TYPED_TEST_P(IommuContract, ARecordedFaultRaisesTheLineUntilSoftwareClearsIt) {
  this->PlantAPageThatIsNotValid();
  std::uint32_t pending = 0;
  bool raised = false;
  bool lowered = true;
  this->Run(
      [&](BusDriver& firmware) {
        this->StartTheFaultQueue(firmware);
        this->UseTheDirectory(firmware);
        this->WaitForTheDevice(firmware);
        pending = firmware.Read32(this->kIpsr);
        raised = this->line_.read();
        firmware.Write32(this->kIpsr, this->kFaultQueuePending);
        firmware.WaitFor(sc_core::sc_time{1, sc_core::SC_NS});
        lowered = !this->line_.read();
      },
      [&](BusDriver& device) {
        this->DeviceWrite(device, this->kIova, 0x1234);
      });

  EXPECT_TRUE(pending & this->kFaultQueuePending);
  EXPECT_TRUE(raised);
  EXPECT_TRUE(lowered);
}

// The queue is full when one more record would bring the tail to the head,
// which is where software has read up to. A fault with nowhere to go sets
// FQOF, bit 9 of fqcsr, and the record is lost.
TYPED_TEST_P(IommuContract, AFaultWhenTheFaultQueueIsFullSetsOverflow) {
  this->PlantAPageThatIsNotValid();
  std::uint32_t fqcsr = 0;
  std::uint32_t tail = 0;
  this->Run(
      [&](BusDriver& firmware) {
        this->StartTheFaultQueue(firmware);
        this->FillTheFaultQueue(firmware);
        this->UseTheDirectory(firmware);
        this->WaitForTheDevice(firmware);
        fqcsr = firmware.Read32(this->kFqcsr);
        tail = firmware.Read32(this->kFqt);
      },
      [&](BusDriver& device) {
        this->DeviceWrite(device, this->kIova, 0x1234);
      });

  EXPECT_TRUE(fqcsr & this->kOverflow);
  EXPECT_EQ(tail, 0U);
  EXPECT_EQ(this->RecordAt(0), (typename TestFixture::FaultRecord{0, 0}));
}

// Linux's fault handler clears an overflow by writing fqcsr back with FQOF
// set, the fault queue still on.
TYPED_TEST_P(IommuContract, SoftwareClearsAnOverflowByWritingIt) {
  this->PlantAPageThatIsNotValid();
  std::uint32_t fqcsr = this->kOverflow;
  this->Run(
      [&](BusDriver& firmware) {
        this->StartTheFaultQueue(firmware);
        this->FillTheFaultQueue(firmware);
        this->UseTheDirectory(firmware);
        this->WaitForTheDevice(firmware);
        firmware.Write32(this->kFqcsr, firmware.Read32(this->kFqcsr));
        fqcsr = firmware.Read32(this->kFqcsr);
      },
      [&](BusDriver& device) {
        this->DeviceWrite(device, this->kIova, 0x1234);
      });

  EXPECT_EQ(fqcsr & (this->kOverflow | this->kOn), this->kOn);
}

TYPED_TEST_P(IommuContract, AFaultWhileTheFaultQueueIsOffIsRecordedNowhere) {
  this->PlantAPageThatIsNotValid();
  std::uint32_t tail = 0;
  std::uint32_t pending = 0;
  this->Run(
      [&](BusDriver& firmware) {
        this->UseTheDirectory(firmware);
        this->WaitForTheDevice(firmware);
        tail = firmware.Read32(this->kFqt);
        pending = firmware.Read32(this->kIpsr);
      },
      [&](BusDriver& device) {
        this->DeviceWrite(device, this->kIova, 0x1234);
      });

  EXPECT_EQ(tail, 0U);
  EXPECT_FALSE(pending & this->kFaultQueuePending);
  // Where a record would have gone, with nothing in the fault queue's base.
  EXPECT_EQ(this->InMemory64(0), 0U);
}

// A command the IOMMU does not have is for software's attention too: IPSR's
// CIP, and the line while the command queue's interrupt is enabled.
TYPED_TEST_P(IommuContract, ACommandItDoesNotHaveRaisesTheLine) {
  this->PlantCommands({this->kAtsInvalidate});
  std::uint32_t pending = 0;
  bool raised = false;
  this->Run(
      [&](BusDriver& firmware) {
        this->StartTheCommandQueue(firmware);
        firmware.Write32(this->kCqt, 1);
        pending =
            this->OnceSet(firmware, this->kIpsr, this->kCommandQueuePending);
        raised = this->line_.read();
      },
      [](BusDriver&) {});

  EXPECT_TRUE(pending & this->kCommandQueuePending);
  EXPECT_TRUE(raised);
}

// There is one line, so every cause is on vector 0, whatever is asked:
// Linux asks for each vector modulo how many lines it was given, and
// checks none it reads back is beyond them.
TYPED_TEST_P(IommuContract, EveryCauseIsOnTheOneLineThereIs) {
  constexpr std::uint64_t kEachOnVector1 = 0x1111;
  std::uint64_t icvec = kEachOnVector1;
  tlm::tlm_response_status written = tlm::TLM_INCOMPLETE_RESPONSE;
  this->Run(
      [&](BusDriver& firmware) {
        written = firmware.Write64(this->kIcvec, kEachOnVector1);
        icvec = firmware.Read64(this->kIcvec);
      },
      [](BusDriver&) {});

  EXPECT_EQ(written, tlm::TLM_OK_RESPONSE);
  EXPECT_EQ(icvec, 0U);
}

// What a driver does about a command the IOMMU does not have: puts one it
// has in its place and clears cmd_ill, and the queue carries on from there.
TYPED_TEST_P(IommuContract, ClearingAnIllegalCommandLetsTheQueueCarryOn) {
  this->PlantCommands({this->kAtsInvalidate, this->kFence});
  std::uint32_t head = 0;
  this->Run(
      [&](BusDriver& firmware) {
        this->StartTheCommandQueue(firmware);
        firmware.Write32(this->kCqt, 2);
        const std::uint32_t cqcsr =
            this->OnceSet(firmware, this->kCqcsr, this->kCommandIllegal);
        this->PlantCommands({this->kInvalidatePageTables, this->kFence});
        firmware.Write32(this->kCqcsr, cqcsr);
        head = this->HeadOnceAt(firmware, 2);
      },
      [](BusDriver&) {});

  EXPECT_EQ(head, 2U);
}

// A queue the IOMMU cannot read or write is a memory fault, bit 8 of the
// queue's control and status register, not a command it does not have.
TYPED_TEST_P(IommuContract, ACommandQueueNothingAnswersForStopsAtAMemoryFault) {
  // Past the end of the memory behind the IOMMU.
  constexpr std::uint64_t kNowhere = 0x20'0000;
  std::uint32_t cqcsr = 0;
  this->Run(
      [&](BusDriver& firmware) {
        firmware.Write64(this->kCqb,
                         this->QueueBase(kNowhere, this->kQueueLog2));
        firmware.Write32(this->kCqcsr, this->kEnable);
        firmware.Write32(this->kCqt, 1);
        cqcsr = this->OnceSet(firmware, this->kCqcsr,
                              this->kMemoryFault | this->kCommandIllegal);
      },
      [](BusDriver&) {});

  EXPECT_EQ(cqcsr & (this->kMemoryFault | this->kCommandIllegal),
            this->kMemoryFault);
}

TYPED_TEST_P(IommuContract, AFaultRecordNothingTakesIsAMemoryFault) {
  // Past the end of the memory behind the IOMMU.
  constexpr std::uint64_t kNowhere = 0x20'0000;
  this->PlantAPageThatIsNotValid();
  std::uint32_t fqcsr = 0;
  std::uint32_t tail = 0;
  this->Run(
      [&](BusDriver& firmware) {
        firmware.Write64(this->kFqb,
                         this->QueueBase(kNowhere, this->kQueueLog2));
        firmware.Write32(this->kFqcsr, this->kEnable);
        this->UseTheDirectory(firmware);
        this->WaitForTheDevice(firmware);
        fqcsr = firmware.Read32(this->kFqcsr);
        tail = firmware.Read32(this->kFqt);
      },
      [&](BusDriver& device) {
        this->DeviceWrite(device, this->kIova, 0x1234);
      });

  EXPECT_TRUE(fqcsr & this->kMemoryFault);
  EXPECT_EQ(tail, 0U);
}

// The line says whether anything pending may interrupt, whichever of the
// two changed last.
TYPED_TEST_P(IommuContract, EnablingAnInterruptThatIsPendingRaisesTheLine) {
  this->PlantCommands({this->kAtsInvalidate});
  bool before = true;
  bool after = false;
  this->Run(
      [&](BusDriver& firmware) {
        firmware.Write64(
            this->kCqb, this->QueueBase(this->kCommandQueue, this->kQueueLog2));
        firmware.Write32(this->kCqcsr, this->kEnable);
        firmware.Write32(this->kCqt, 1);
        this->OnceSet(firmware, this->kIpsr, this->kCommandQueuePending);
        before = this->line_.read();
        firmware.Write32(this->kCqcsr, this->kEnable | this->kInterruptEnable);
        firmware.WaitFor(this->BetweenPolls());
        after = this->line_.read();
      },
      [](BusDriver&) {});

  EXPECT_FALSE(before);
  EXPECT_TRUE(after);
}

// What a debugger, or Python's peek, does: reads a register by debug
// transport, in no simulated time.
TYPED_TEST_P(IommuContract, ADebuggerReadsItsRegisters) {
  std::array<std::uint8_t, 8> bytes{};
  unsigned read = 0;
  this->Run(
      [&](BusDriver& firmware) {
        read = firmware.DebugRead(this->kCapabilities, bytes);
      },
      [](BusDriver&) {});

  EXPECT_EQ(read, bytes.size());
  // VERSION, bits 7:0, is 1.0.
  EXPECT_EQ(bytes[0], 0x10U);
}

// A write is firmware's, with all it sets going, which a debugger's look
// must not: one that wrote the command queue's tail would run commands.
TYPED_TEST_P(IommuContract, ADebuggerCannotWriteItsRegisters) {
  const std::array<std::uint8_t, 4> one{1, 0, 0, 0};
  unsigned written = 1;
  std::uint32_t tail = 1;
  this->Run(
      [&](BusDriver& firmware) {
        written = firmware.DebugWrite(this->kCqt, one);
        tail = firmware.Read32(this->kCqt);
      },
      [](BusDriver&) {});

  EXPECT_EQ(written, 0U);
  EXPECT_EQ(tail, 0U);
}

// fctl's WSI, bit 1, says the IOMMU interrupts by wire. An IOMMU that has
// wires alone has it set, and Linux reads it before it asks for wires.
TYPED_TEST_P(IommuContract, ItsInterruptsAreWiredWhateverIsWrittenToFctl) {
  constexpr std::uint32_t kWiredInterrupts = 1U << 1U;
  tlm::tlm_response_status written = tlm::TLM_INCOMPLETE_RESPONSE;
  std::uint32_t fctl = 0;
  this->Run(
      [&](BusDriver& firmware) {
        written = firmware.Write32(this->kFctl, 0);
        fctl = firmware.Read32(this->kFctl);
      },
      [](BusDriver&) {});

  EXPECT_EQ(written, tlm::TLM_OK_RESPONSE);
  EXPECT_TRUE(fctl & kWiredInterrupts);
}

REGISTER_TYPED_TEST_SUITE_P(
    IommuContract, OutOfResetADevicesWriteIsRefusedAndLandsNowhere,
    ADevicesWriteLandsWhereItsPageTablesMapTheAddressItWroteTo,
    AWriteThatCrossesAPageLandsWhereEachPageIsMapped,
    AWriteThatCrossesIntoAPageThatIsNotValidStopsThere,
    AnAccessThatDoesNotSayWhoSentItIsRefused,
    ADirectoryModeTheSpecReservesDoesNotReadBack, AWriteToDdtpCannotMakeItBusy,
    ItsCapabilitiesAreVersion1WithSv39WiredInterruptsAndBaseFormatContexts,
    ACommandQueueOfTheSizeItCanHoldReadsBack, ACommandQueueIsOnWhileItIsEnabled,
    EnablingTheCommandQueueEmptiesIt, EnablingTheFaultQueueEmptiesIt,
    TheCommandQueuesTailIsOnlyAsWideAsTheQueue,
    ACommandQueueThatIsOnRunsItsCommandsToTheTail,
    AFenceThatAsksToBeSeenWritesItsDataWhereItSays,
    ACommandItDoesNotHaveStopsTheQueueAtIt,
    ARefusedAccessIsRecordedAtTheFaultQueuesTail,
    ARecordedFaultRaisesTheLineUntilSoftwareClearsIt,
    AFaultWhenTheFaultQueueIsFullSetsOverflow,
    SoftwareClearsAnOverflowByWritingIt,
    AFaultWhileTheFaultQueueIsOffIsRecordedNowhere,
    ACommandItDoesNotHaveRaisesTheLine, EveryCauseIsOnTheOneLineThereIs,
    ClearingAnIllegalCommandLetsTheQueueCarryOn,
    ACommandQueueNothingAnswersForStopsAtAMemoryFault,
    AFaultRecordNothingTakesIsAMemoryFault,
    EnablingAnInterruptThatIsPendingRaisesTheLine, ADebuggerReadsItsRegisters,
    ADebuggerCannotWriteItsRegisters,
    ItsInterruptsAreWiredWhateverIsWrittenToFctl);

#endif  // TESTS_CPP_CONTRACTS_IOMMU_CONTRACT_H_
