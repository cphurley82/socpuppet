#ifndef TESTS_CPP_SUPPORT_SSD_FIRMWARE_H_
#define TESTS_CPP_SUPPORT_SSD_FIRMWARE_H_

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <utility>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "socpuppet/platform/transport.h"
#include "socpuppet/regs/command_device.h"
#include "socpuppet/regs/dma_engine.h"

// Where the firmware finds the SSD's hardware on its bus: the three
// devices' register blocks, and the buffer, which is the SSD's own memory.
struct SsdMap {
  std::uint64_t frontend = 0;
  std::uint64_t dma = 0;
  std::uint64_t flash = 0;
  std::uint64_t buffer = 0;
};

// A stand-in for an SSD's firmware, in the place of its CPU: what the
// firmware would do, done by a simulation thread in plain C++, with no
// processor and no instructions. It is a test's own, written from the
// NVMe specification and from the register tables of the three devices
// (docs/models/nvme-frontend.md, dma-engine.md and flash-controller.md),
// and it shares nothing with the models it drives.
//
// It does what the NVMe contract asks of a drive, and no more: Identify,
// the number of queues, creating I/O queues, and Read, Write and Flush
// on one namespace of 512-byte blocks.
//
// Its flash translation layer is a map from each of the drive's pages to
// the NAND page that holds it. A page that was never written has none, and
// reads as zeros. A page written for the first time takes the next NAND
// page nobody has, and one written again is programmed where it is, which
// only an ideal NAND allows.
class SsdFirmware : public sc_core::sc_module {
 public:
  tlm_utils::simple_initiator_socket<SsdFirmware> socket{"socket"};
  // The frontend's line to its CPU.
  sc_core::sc_in<bool> irq{"irq"};

  SsdFirmware(const sc_core::sc_module_name& name, const SsdMap& map)
      : sc_module(name), map_(map) {
    SC_THREAD(Run);
  }

 private:
  // ---- The frontend's registers for its CPU.
  enum Frontend : std::uint64_t {
    kControl = 0x00,
    kStatus = 0x04,
    kInterruptEnable = 0x08,
    kLimits = 0x0C,
    kCommandQueue = 0x10,
    kCompletionResult = 0x14,
    kCompletionStatus = 0x18,
    kCompletionPost = 0x1C,
    kQueueId = 0x20,
    kQueueBaseLow = 0x24,
    kQueueBaseHigh = 0x28,
    kQueueLast = 0x2C,
    kQueueLink = 0x30,
    kQueueCreate = 0x34,
    kCommand = 0x40,
  };
  enum FrontendStatus : std::uint32_t {
    kEnabled = 1U << 0,
    kDisabled = 1U << 1,
    kCommandWaiting = 1U << 2,
  };
  static constexpr std::uint32_t kReady = 1U << 0;
  static constexpr std::uint32_t kCreateCompletionQueue = 1;
  static constexpr std::uint32_t kCreateSubmissionQueue = 2;

  // ---- The flash controller's registers.
  enum Flash : std::uint64_t {
    kBlock = 0x0C,
    kPage = 0x10,
    kFlashLocalAddress = 0x14,
    kPageSize = 0x20,
    kPagesPerBlock = 0x24,
    kBlocks = 0x28,
  };
  static constexpr std::uint32_t kReadPage = 1;
  static constexpr std::uint32_t kProgramPage = 2;
  static constexpr std::uint32_t kIdentify = 4;

  // ---- NVMe, as its specification gives it.
  static constexpr std::size_t kCommandBytes = 64;
  // The drive's block, and the page of the host's memory that a command's
  // data pointers count in.
  static constexpr std::uint32_t kBlockSize = 512;
  static constexpr std::uint32_t kHostPage = 4096;
  // There is one namespace, and namespaces are numbered from 1.
  static constexpr std::uint32_t kTheNamespace = 1;

  enum AdminOpcode : std::uint8_t {
    kCreateIoSubmissionQueue = 0x01,
    kCreateIoCompletionQueue = 0x05,
    kIdentifyOpcode = 0x06,
    kSetFeatures = 0x09,
  };
  enum IoOpcode : std::uint8_t {
    kFlush = 0x00,
    kWrite = 0x01,
    kRead = 0x02,
  };
  // What Identify can be asked for, and the one feature there is to set.
  enum IdentifyWhat : std::uint8_t {
    kTheNamespaceItself = 0x00,
    kTheController = 0x01,
    kTheActiveNamespaces = 0x02,
  };
  static constexpr std::uint8_t kNumberOfQueues = 0x07;

  // How a command went: what its completion will say. A status is from
  // the list every command shares (type 0) or from the command's own
  // (type 1).
  struct Outcome {
    std::uint8_t status = 0;
    std::uint8_t status_type = 0;
    std::uint32_t result = 0;
  };
  enum GenericStatus : std::uint8_t {
    kInvalidOpcode = 0x01,
    kInvalidField = 0x02,
    kDataTransferError = 0x04,
    kInvalidNamespace = 0x0B,
    kLbaOutOfRange = 0x80,
  };
  enum QueueStatus : std::uint8_t {
    kCompletionQueueInvalid = 0x00,
    kInvalidQueueIdentifier = 0x01,
    kInvalidQueueSize = 0x02,
    kInvalidInterruptVector = 0x08,
  };
  static Outcome Generic(std::uint8_t status) { return {.status = status}; }
  static Outcome OfTheCommand(std::uint8_t status) {
    return {.status = status, .status_type = 1};
  }

  // A command, with the fields of it the firmware reads.
  struct Command {
    std::array<std::uint8_t, kCommandBytes> bytes{};

    std::uint8_t Opcode() const { return bytes[0]; }
    std::uint32_t NamespaceId() const { return Dword(1); }
    // Where the command's data is in the host's memory: its first page,
    // and either its second or a list of the rest.
    std::uint64_t Prp1() const { return Qword(24); }
    std::uint64_t Prp2() const { return Qword(32); }
    // A command's own parameters, which each command lays out its own way.
    std::uint32_t Dword(std::size_t number) const {
      return socpuppet::LoadLittleEndian<std::uint32_t>(
          std::span{bytes}.subspan(4 * number));
    }
    std::uint64_t Qword(std::size_t offset) const {
      return socpuppet::LoadLittleEndian<std::uint64_t>(
          std::span{bytes}.subspan(offset));
    }
  };

  // A run of bytes in the host's memory.
  struct Extent {
    std::uint64_t address = 0;
    std::uint32_t length = 0;
  };

  // ---- The buffer: a page of the drive being read or written, and a
  // page of scratch for what is made up to send or fetched to be read.
  std::uint64_t PageBuffer() const { return map_.buffer; }
  std::uint64_t Scratch() const { return map_.buffer + kHostPage; }

  // ---- The bus. The firmware asks its hardware for nothing the hardware
  // would refuse, so a refusal is a failure of the test, and the firmware
  // stops: the host then waits in vain, and its patience runs out in
  // simulated time.
  std::uint32_t Read32(std::uint64_t address) {
    std::array<std::uint8_t, 4> bytes{};
    Read(address, bytes);
    return socpuppet::LoadLittleEndian<std::uint32_t>(bytes);
  }
  void Write32(std::uint64_t address, std::uint32_t value) {
    Write(address, socpuppet::LittleEndianBytes(value));
  }
  void Read(std::uint64_t address, std::span<std::uint8_t> out) {
    Check(socpuppet::Transport(socket, tlm::TLM_READ_COMMAND, address, out),
          "read", address);
  }
  void Write(std::uint64_t address, std::span<const std::uint8_t> in) {
    Check(socpuppet::Transport(socket, tlm::TLM_WRITE_COMMAND, address,
                               socpuppet::WriteData(in)),
          "write", address);
  }
  void Check(tlm::tlm_response_status response, const char* access,
             std::uint64_t address) {
    if (response == tlm::TLM_OK_RESPONSE) return;
    ADD_FAILURE() << "The SSD's hardware refused its firmware's " << access
                  << " at 0x" << std::hex << address << ": "
                  << socpuppet::ResponseString(response) << ".";
    stopped_ = true;
  }

  // Gives the DMA engine or the flash controller a command and waits for
  // it. Returns whether it was carried out.
  bool Do(std::uint64_t device, std::uint32_t command) {
    Write32(device + COMMAND_DEVICE_COMMAND, command);
    std::uint32_t status = Read32(device + COMMAND_DEVICE_STATUS);
    // Nothing takes simulated time yet, so the device is done within a
    // delta cycle or two. The limit is there so that one that never
    // finishes fails the test and does not hang it.
    for (int turn = 0; (status & COMMAND_DEVICE_STATUS_BUSY) != 0; ++turn) {
      if (turn == kPatienceInDeltaCycles) {
        ADD_FAILURE() << "The device at 0x" << std::hex << device
                      << " is still busy.";
        stopped_ = true;
        return false;
      }
      wait(sc_core::SC_ZERO_TIME);
      status = Read32(device + COMMAND_DEVICE_STATUS);
    }
    return (status & COMMAND_DEVICE_STATUS_ERROR) == 0;
  }

  // Copies between the host's memory and the buffer.
  bool Copy(std::uint32_t direction, std::uint64_t host_address,
            std::uint64_t local_address, std::uint32_t length) {
    Write32(map_.dma + DMA_ENGINE_HOST_ADDRESS_LOW,
            static_cast<std::uint32_t>(host_address));
    Write32(map_.dma + DMA_ENGINE_HOST_ADDRESS_HIGH,
            static_cast<std::uint32_t>(host_address >> 32));
    Write32(map_.dma + DMA_ENGINE_LOCAL_ADDRESS,
            static_cast<std::uint32_t>(local_address));
    Write32(map_.dma + DMA_ENGINE_LENGTH, length);
    return Do(map_.dma, direction);
  }

  // Moves a NAND page between the chip and the page buffer.
  bool Flash(std::uint32_t command, std::uint32_t nand_page) {
    Write32(map_.flash + kBlock, nand_page / pages_per_block_);
    Write32(map_.flash + kPage, nand_page % pages_per_block_);
    Write32(map_.flash + kFlashLocalAddress,
            static_cast<std::uint32_t>(PageBuffer()));
    return Do(map_.flash, command);
  }

  // ---- The firmware.
  void Run() {
    StartUp();
    while (!stopped_) {
      while (!irq.read()) wait(irq.posedge_event());
      const std::uint32_t status = Read32(map_.frontend + kStatus);
      // The reset first: what the host enabled is the controller as it is
      // after it.
      if ((status & kDisabled) != 0) TheHostResetTheController();
      if ((status & kEnabled) != 0) TheHostEnabledTheController();
      if ((status & kCommandWaiting) != 0) DealWithTheCommand();
      // What was just done may have lowered the line, which shows a delta
      // cycle later.
      wait(sc_core::SC_ZERO_TIME);
    }
  }

  void StartUp() {
    Do(map_.flash, kIdentify);
    page_size_ = Read32(map_.flash + kPageSize);
    pages_per_block_ = Read32(map_.flash + kPagesPerBlock);
    const std::uint32_t pages = pages_per_block_ * Read32(map_.flash + kBlocks);
    where_.assign(pages, std::nullopt);
    const std::uint32_t limits = Read32(map_.frontend + kLimits);
    io_queue_pairs_ = limits & 0xFFFF;
    vectors_ = limits >> 16;
    // By identifier, and identifiers count from 1.
    completion_queues_.assign(io_queue_pairs_ + 1, false);
    submission_queues_.assign(io_queue_pairs_ + 1, false);
    Write32(map_.frontend + kInterruptEnable,
            kEnabled | kDisabled | kCommandWaiting);
  }

  // A controller reset: the queues are gone, and what is on the drive
  // stays. The acknowledgement comes last, because it says the firmware
  // has let go of everything from before.
  void TheHostResetTheController() {
    completion_queues_.assign(completion_queues_.size(), false);
    submission_queues_.assign(submission_queues_.size(), false);
    Write32(map_.frontend + kStatus, kDisabled);
  }

  // There is nothing to start up, so the firmware is ready at once. If
  // the host has changed its mind again by now, the frontend does not
  // hear it, and says so in its own time.
  void TheHostEnabledTheController() {
    Write32(map_.frontend + kStatus, kEnabled);
    Write32(map_.frontend + kControl, kReady);
  }

  void DealWithTheCommand() {
    Command command;
    Read(map_.frontend + kCommand, command.bytes);
    const bool is_admin = Read32(map_.frontend + kCommandQueue) == 0;
    const Outcome outcome = is_admin ? Admin(command) : Io(command);
    Write32(map_.frontend + kCompletionResult, outcome.result);
    Write32(map_.frontend + kCompletionStatus,
            std::uint32_t{outcome.status_type} << 8 | outcome.status);
    Write32(map_.frontend + kCompletionPost, 1);
  }

  // ---- Admin commands.
  Outcome Admin(const Command& command) {
    switch (command.Opcode()) {
      case kCreateIoCompletionQueue:
        return CreateCompletionQueue(command);
      case kCreateIoSubmissionQueue:
        return CreateSubmissionQueue(command);
      case kIdentifyOpcode:
        return Identify(command);
      case kSetFeatures:
        return SetFeatures(command);
      default:
        return Generic(kInvalidOpcode);
    }
  }

  // Both kinds of queue are asked for the same way: the identifier in the
  // low half of dword 10, the size (counted from zero) in the high half,
  // and where the queue is in the first data pointer.
  static std::uint32_t QueueId(const Command& command) {
    return command.Dword(10) & 0xFFFF;
  }
  static std::uint32_t LastSlot(const Command& command) {
    return command.Dword(10) >> 16;
  }
  // Whether the host may create an I/O queue with this identifier: queue
  // 0 is the admin queue, and there are only so many.
  bool IsAnIoQueue(std::uint32_t queue_id) const {
    return queue_id != 0 && queue_id <= io_queue_pairs_;
  }

  void HaveItCreated(std::uint32_t kind, const Command& command,
                     std::uint32_t link) {
    Write32(map_.frontend + kQueueId, QueueId(command));
    Write32(map_.frontend + kQueueBaseLow,
            static_cast<std::uint32_t>(command.Prp1()));
    Write32(map_.frontend + kQueueBaseHigh,
            static_cast<std::uint32_t>(command.Prp1() >> 32));
    Write32(map_.frontend + kQueueLast, LastSlot(command));
    Write32(map_.frontend + kQueueLink, link);
    Write32(map_.frontend + kQueueCreate, kind);
  }

  Outcome CreateCompletionQueue(const Command& command) {
    const std::uint32_t queue_id = QueueId(command);
    if (!IsAnIoQueue(queue_id) || completion_queues_[queue_id]) {
      return OfTheCommand(kInvalidQueueIdentifier);
    }
    // A queue keeps one slot empty, so one of a single entry holds nothing.
    if (LastSlot(command) == 0) return OfTheCommand(kInvalidQueueSize);
    const std::uint32_t vector = command.Dword(11) >> 16;
    if (vector >= vectors_) return OfTheCommand(kInvalidInterruptVector);
    HaveItCreated(kCreateCompletionQueue, command, vector);
    completion_queues_[queue_id] = true;
    return {};
  }

  Outcome CreateSubmissionQueue(const Command& command) {
    const std::uint32_t queue_id = QueueId(command);
    if (!IsAnIoQueue(queue_id) || submission_queues_[queue_id]) {
      return OfTheCommand(kInvalidQueueIdentifier);
    }
    if (LastSlot(command) == 0) return OfTheCommand(kInvalidQueueSize);
    // Its commands' completions go to a completion queue, which has to be
    // there first. The admin completion queue always is.
    const std::uint32_t completion_queue = command.Dword(11) >> 16;
    const bool is_there =
        completion_queue == 0 ||
        (IsAnIoQueue(completion_queue) && completion_queues_[completion_queue]);
    if (!is_there) return OfTheCommand(kCompletionQueueInvalid);
    HaveItCreated(kCreateSubmissionQueue, command, completion_queue);
    submission_queues_[queue_id] = true;
    return {};
  }

  // Identify: a 4 KiB page that describes the controller, a namespace, or
  // which namespaces there are.
  Outcome Identify(const Command& command) {
    std::vector<std::uint8_t> page(kHostPage);
    const std::span<std::uint8_t> bytes{page};
    switch (command.Dword(10) & 0xFF) {
      case kTheController:
        // How many namespaces there are, at offset 516.
        socpuppet::StoreLittleEndian(std::uint32_t{1}, bytes.subspan(516));
        break;
      case kTheNamespaceItself:
        if (command.NamespaceId() != kTheNamespace) {
          return Generic(kInvalidNamespace);
        }
        // Its size and its capacity in blocks, and at offset 128 the first
        // block format, whose third byte is the block size as a power of
        // two: 2 to the 9th is 512.
        socpuppet::StoreLittleEndian(DriveBlocks(), bytes.subspan(0));
        socpuppet::StoreLittleEndian(DriveBlocks(), bytes.subspan(8));
        page[130] = 9;
        break;
      case kTheActiveNamespaces:
        socpuppet::StoreLittleEndian(kTheNamespace, bytes.subspan(0));
        break;
      default:
        return Generic(kInvalidField);
    }
    Write(Scratch(), page);
    return CopyToTheHost(command, Scratch(), kHostPage);
  }

  Outcome SetFeatures(const Command& command) const {
    if ((command.Dword(10) & 0xFF) != kNumberOfQueues) {
      return Generic(kInvalidField);
    }
    // The answer is how many I/O queues the controller has, whatever the
    // host asked for, counted from zero: submission queues in the low
    // half, completion queues in the high half.
    const std::uint32_t from_zero = io_queue_pairs_ - 1;
    return {.result = from_zero << 16 | from_zero};
  }

  // ---- I/O commands.
  Outcome Io(const Command& command) {
    switch (command.Opcode()) {
      case kFlush:
        // Everything written is already in the NAND.
        return {};
      case kRead:
      case kWrite:
        return ReadOrWrite(command);
      default:
        return Generic(kInvalidOpcode);
    }
  }

  std::uint64_t DriveBlocks() const {
    return std::uint64_t{where_.size()} * (page_size_ / kBlockSize);
  }

  Outcome ReadOrWrite(const Command& command) {
    if (command.NamespaceId() != kTheNamespace) {
      return Generic(kInvalidNamespace);
    }
    // The first block is in dwords 10 and 11, and how many, counted from
    // zero, in the low half of dword 12.
    const std::uint64_t first =
        std::uint64_t{command.Dword(11)} << 32 | command.Dword(10);
    const std::uint64_t count = (command.Dword(12) & 0xFFFF) + std::uint64_t{1};
    if (first > DriveBlocks() || count > DriveBlocks() - first) {
      return Generic(kLbaOutOfRange);
    }
    const bool writing = command.Opcode() == kWrite;
    const std::optional<std::vector<Extent>> extents =
        DataOf(command, static_cast<std::uint32_t>(count * kBlockSize));
    if (!extents) return Generic(kDataTransferError);

    // Through the host's memory an extent at a time, and through the
    // drive a page at a time, whichever ends first.
    std::uint64_t at = first * kBlockSize;
    for (Extent extent : *extents) {
      while (extent.length != 0) {
        const auto page = static_cast<std::uint32_t>(at / page_size_);
        const auto offset = static_cast<std::uint32_t>(at % page_size_);
        const std::uint32_t length =
            std::min(extent.length, page_size_ - offset);
        const bool ok =
            writing ? WriteIntoPage(page, offset, extent.address, length)
                    : ReadFromPage(page, offset, extent.address, length);
        if (!ok) return Generic(kDataTransferError);
        at += length;
        extent.address += length;
        extent.length -= length;
      }
    }
    return {};
  }

  // Puts one of the drive's pages in the page buffer: from the NAND, or
  // as zeros if it was never written.
  bool Load(std::uint32_t page) {
    const std::optional<std::uint32_t> nand_page = where_[page];
    if (nand_page) return Flash(kReadPage, *nand_page);
    Write(PageBuffer(), std::vector<std::uint8_t>(page_size_, 0));
    return true;
  }

  bool ReadFromPage(std::uint32_t page, std::uint32_t offset,
                    std::uint64_t host_address, std::uint32_t length) {
    return Load(page) && Copy(DMA_ENGINE_COMMAND_TO_HOST, host_address,
                              PageBuffer() + offset, length);
  }

  // What is not being written of the page has to survive, so the page is
  // read, changed and programmed again. A page written for the first time
  // takes the next NAND page nobody has.
  bool WriteIntoPage(std::uint32_t page, std::uint32_t offset,
                     std::uint64_t host_address, std::uint32_t length) {
    if (!Load(page) || !Copy(DMA_ENGINE_COMMAND_FROM_HOST, host_address,
                             PageBuffer() + offset, length)) {
      return false;
    }
    const std::uint32_t nand_page = where_[page].value_or(next_free_nand_page_);
    if (!where_[page]) {
      where_[page] = nand_page;
      ++next_free_nand_page_;
    }
    return Flash(kProgramPage, nand_page);
  }

  // ---- A command's data.
  // Where in the host's memory `length` bytes of a command's data are, or
  // nothing if the host's list of them could not be fetched. The first
  // pointer is to the data itself, and may start anywhere in a page. If
  // what is left fits in one page, the second pointer is to that page.
  // Otherwise it is to a list of pointers, a page each, whose last entry
  // points on to more of the list if the list fills its own page.
  std::optional<std::vector<Extent>> DataOf(const Command& command,
                                            std::uint32_t length) {
    std::vector<Extent> extents;
    const std::uint32_t in_the_first =
        std::min(length, kHostPage - PageOffset(command.Prp1()));
    extents.push_back({.address = command.Prp1(), .length = in_the_first});
    std::uint32_t left = length - in_the_first;
    if (left == 0) return extents;
    if (left <= kHostPage) {
      extents.push_back({.address = command.Prp2(), .length = left});
      return extents;
    }
    std::uint64_t list = command.Prp2();
    while (left != 0) {
      // As much of the list as its page holds, fetched into the scratch
      // page to be read.
      const std::uint32_t list_bytes = kHostPage - PageOffset(list);
      if (!Copy(DMA_ENGINE_COMMAND_FROM_HOST, list, Scratch(), list_bytes))
        return std::nullopt;
      std::vector<std::uint8_t> entries(list_bytes);
      Read(Scratch(), entries);
      const std::size_t count = list_bytes / 8;
      for (std::size_t index = 0; index < count && left != 0; ++index) {
        const auto entry = socpuppet::LoadLittleEndian<std::uint64_t>(
            std::span{entries}.subspan(8 * index));
        // The last entry of a full list points on, if more than one page
        // of data is still to come.
        if (index == count - 1 && left > kHostPage) {
          list = entry;
          break;
        }
        const std::uint32_t here = std::min(left, kHostPage);
        extents.push_back({.address = entry, .length = here});
        left -= here;
      }
    }
    return extents;
  }

  static std::uint32_t PageOffset(std::uint64_t address) {
    return static_cast<std::uint32_t>(address % kHostPage);
  }

  // Sends what the buffer holds at `local_address` to where a command's
  // data goes in the host's memory.
  Outcome CopyToTheHost(const Command& command, std::uint64_t local_address,
                        std::uint32_t length) {
    const std::optional<std::vector<Extent>> extents = DataOf(command, length);
    if (!extents) return Generic(kDataTransferError);
    for (const Extent& extent : *extents) {
      if (!Copy(DMA_ENGINE_COMMAND_TO_HOST, extent.address, local_address,
                extent.length)) {
        return Generic(kDataTransferError);
      }
      local_address += extent.length;
    }
    return {};
  }

  // How many delta cycles the firmware gives a device to finish.
  static constexpr int kPatienceInDeltaCycles = 100;

  SsdMap map_;
  // Set when the hardware has refused the firmware something.
  bool stopped_ = false;
  // What the hardware said it has.
  std::uint32_t page_size_ = 0;
  std::uint32_t pages_per_block_ = 0;
  std::uint32_t io_queue_pairs_ = 0;
  std::uint32_t vectors_ = 0;
  // The I/O queues the host has had created, by identifier.
  std::vector<bool> completion_queues_;
  std::vector<bool> submission_queues_;
  // The flash translation layer: for each of the drive's pages, the NAND
  // page that holds it, if it was ever written. And the next NAND page
  // nobody has.
  std::vector<std::optional<std::uint32_t>> where_;
  std::uint32_t next_free_nand_page_ = 0;
};

// The firmware stand-in, put into a registry so that a platform can be
// composed with it by name. Ports: "socket" and "irq".
inline void AddSsdFirmware(socpuppet::Registry& registry,
                           std::string implementation, const SsdMap& map) {
  registry.Add(std::move(implementation),
               [map](const char* name, socpuppet::Parameters&) {
                 auto module = std::make_unique<SsdFirmware>(name, map);
                 std::vector<socpuppet::Port> ports{
                     socpuppet::InitiatorPort("socket", module->socket),
                     socpuppet::WireSinkPort("irq", module->irq)};
                 return socpuppet::Instance{.module = std::move(module),
                                            .ports = std::move(ports)};
               });
}

#endif  // TESTS_CPP_SUPPORT_SSD_FIRMWARE_H_
