#ifndef TESTS_CPP_SUPPORT_NVME_HOST_H_
#define TESTS_CPP_SUPPORT_NVME_HOST_H_

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <ios>
#include <optional>
#include <span>
#include <utility>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "tests/cpp/contracts/bus_driver.h"
#include "tests/cpp/support/line_watcher.h"

// A small NVMe host for tests: just enough of a driver to bring a
// controller up, hand it commands and collect their completions. It runs
// inside a BusDriver's thread, and keeps its queues in the host's memory,
// where the controller reaches them by DMA.
//
// Everything here is written from the NVMe base specification (register
// offsets, the 64-byte command, the 16-byte completion), and none of it is
// shared with the code under test.
class NvmeHost {
 public:
  // A command, as far as the tests fill one in.
  struct Command {
    std::uint8_t opcode = 0;
    std::uint32_t namespace_id = 0;
    // Where in the host's memory the command's data is. The specification
    // calls these two PRP entries: `data` is the first page, and
    // `more_data` is the second page, or a list of the pages after the
    // first if there are more than two.
    std::uint64_t data = 0;
    std::uint64_t more_data = 0;
    // What the command is to do, in a form of its own for each opcode:
    // the 32-bit words the specification calls command dwords 10 to 12.
    std::uint32_t dword10 = 0;
    std::uint32_t dword11 = 0;
    std::uint32_t dword12 = 0;
  };

  // What a namespace says about itself.
  struct Namespace {
    std::uint64_t blocks = 0;
    std::uint32_t block_size = 0;
  };

  // What the controller says about a command it has finished.
  struct Completion {
    std::uint16_t command_id = 0;
    // The status code and its type. Zero is success. The hints about
    // retrying that share the field are left out.
    std::uint16_t status = 0;
    // How far the controller had read the submission queue by then: the
    // slot it will fetch its next command from.
    std::uint16_t submission_queue_head = 0;
    // What the command has to say for itself, if anything (dword 0).
    std::uint32_t result = 0;
  };

  // Status values: the status code in bits 7:0, its type in bits 10:8.
  static constexpr std::uint16_t kInvalidCommandOpcode = 0x001;
  static constexpr std::uint16_t kInvalidField = 0x002;
  static constexpr std::uint16_t kInvalidNamespace = 0x00B;
  static constexpr std::uint16_t kLbaOutOfRange = 0x080;
  // These two are specific to the commands that create queues (type 1).
  static constexpr std::uint16_t kCompletionQueueInvalid = 0x100;
  static constexpr std::uint16_t kInvalidQueueIdentifier = 0x101;
  static constexpr std::uint16_t kInvalidInterruptVector = 0x108;
  // The controller could not move the command's data to or from the host.
  static constexpr std::uint16_t kDataTransferError = 0x004;

  // Admin opcodes.
  static constexpr std::uint8_t kCreateIoSubmissionQueue = 0x01;
  static constexpr std::uint8_t kCreateIoCompletionQueue = 0x05;
  static constexpr std::uint8_t kIdentify = 0x06;
  static constexpr std::uint8_t kSetFeatures = 0x09;

  // A submission queue and the completion queue its completions go to.
  class QueuePair {
   public:
    QueuePair(std::uint16_t id, std::uint64_t submissions,
              std::uint64_t completions, std::uint16_t entries)
        : id_(id),
          submissions_(submissions),
          completions_(completions),
          entries_(entries) {}

    // How many entries each of the two queues has.
    std::uint16_t Entries() const { return entries_; }

   private:
    friend class NvmeHost;
    std::uint16_t id_;
    // Where the two queues are in the host's memory.
    std::uint64_t submissions_;
    std::uint64_t completions_;
    std::uint16_t entries_;
    // Where the host puts its next command, and looks for the next
    // completion.
    std::uint16_t tail_ = 0;
    std::uint16_t head_ = 0;
    // The phase bit a new completion carries. It starts at 1 and inverts
    // each time the completion queue wraps around.
    bool phase_ = true;
    // How far the host has told the controller it has got.
    std::uint16_t acknowledged_ = 0;
    // Not zero, and not the same byte twice, so that a completion which
    // carries no identifier, or a garbled one, is told apart.
    std::uint16_t next_command_id_ = 0x1234;
  };

  // `registers` is where the controller's register block is on the bus,
  // and `memory` is where the host's own memory starts. `interrupts` are
  // the controller's interrupt lines, by vector.
  NvmeHost(BusDriver& bus, std::uint64_t registers, std::uint64_t memory,
           std::vector<LineWatcher*> interrupts)
      : bus_(bus),
        registers_(registers),
        free_memory_(memory),
        interrupts_(std::move(interrupts)) {}

  // How many entries an I/O queue may have at most (CAP.MQES, which counts
  // from zero). The admin queues have a limit of their own.
  std::uint32_t LargestIoQueueSize() {
    return static_cast<std::uint32_t>(Capabilities() & 0xFFFF) + 1;
  }

  // Tells the controller where the admin queues are, sets CC.EN, and waits
  // for the controller to say it is ready for as long as it says that may
  // take.
  void Enable() {
    Write32(kAdminQueueAttributes,
            std::uint32_t{kQueueEntries - 1} << 16 | (kQueueEntries - 1));
    Write64(kAdminSubmissionQueue, admin_.submissions_);
    Write64(kAdminCompletionQueue, admin_.completions_);
    Write32(kConfiguration, kCommandSizes | kEnable);
    WaitUntilReadyIs(true);
  }

  // Clears CC.EN, which resets the controller, and waits for it to say it
  // is no longer ready. A reset does away with every queue, so the host
  // starts its own over as well, in memory that holds no old entries.
  void Disable() {
    Write32(kConfiguration, Read32(kConfiguration) & ~kEnable);
    WaitUntilReadyIs(false);
    admin_ = QueuePair{0, Allocate(1), Allocate(1), kQueueEntries};
    io_ = QueuePair{1, Allocate(1), Allocate(1), kQueueEntries};
  }

  // CSTS.RDY: whether the controller is ready to take commands.
  bool IsReady() { return (Read32(kStatus) & kReady) != 0; }

  // The admin queues, which exist once the controller is enabled.
  QueuePair& Admin() { return admin_; }

  // Creates I/O queue pair 1 with two admin commands: a completion queue
  // that interrupts on `vector`, then the submission queue that feeds it.
  // Returns false if either command fails.
  bool CreateIoQueues(std::uint16_t vector) {
    const auto completions =
        CreateIoCompletionQueue(io_.id_, io_.completions_, vector);
    const auto submissions =
        CreateIoSubmissionQueue(io_.id_, io_.submissions_, io_.id_);
    return completions && completions->status == 0 && submissions &&
           submissions->status == 0;
  }

  // The two commands on their own. `memory` is where the host has set the
  // queue's ring aside, and each returns what the controller said.
  std::optional<Completion> CreateIoCompletionQueue(std::uint16_t id,
                                                    std::uint64_t memory,
                                                    std::uint16_t vector) {
    // Physically contiguous, with interrupts enabled, on `vector`.
    return Complete(
        admin_, {.opcode = kCreateIoCompletionQueue,
                 .data = memory,
                 .dword10 = std::uint32_t{kQueueEntries - 1} << 16 | id,
                 .dword11 = std::uint32_t{vector} << 16 | kInterruptsEnabled |
                            kContiguous});
  }

  std::optional<Completion> CreateIoSubmissionQueue(
      std::uint16_t id, std::uint64_t memory, std::uint16_t completion_queue) {
    // Physically contiguous, completing into `completion_queue`.
    return Complete(
        admin_,
        {.opcode = kCreateIoSubmissionQueue,
         .data = memory,
         .dword10 = std::uint32_t{kQueueEntries - 1} << 16 | id,
         .dword11 = std::uint32_t{completion_queue} << 16 | kContiguous});
  }

  // The I/O queues, which exist once CreateIoQueues() has made them.
  QueuePair& Io() { return io_; }

  // Puts a command on a submission queue and rings its doorbell. Returns
  // the command identifier that its completion will carry.
  std::uint16_t Submit(QueuePair& queue, const Command& command) {
    const std::uint16_t command_id = queue.next_command_id_++;
    std::array<std::uint8_t, kCommandSize> entry{};
    entry[0] = command.opcode;
    Store<std::uint16_t>(command_id, std::span{entry}.subspan(2));
    Store<std::uint32_t>(command.namespace_id, std::span{entry}.subspan(4));
    Store<std::uint64_t>(command.data, std::span{entry}.subspan(24));
    Store<std::uint64_t>(command.more_data, std::span{entry}.subspan(32));
    Store<std::uint32_t>(command.dword10, std::span{entry}.subspan(40));
    Store<std::uint32_t>(command.dword11, std::span{entry}.subspan(44));
    Store<std::uint32_t>(command.dword12, std::span{entry}.subspan(48));
    WriteMemory(queue.submissions_ + (queue.tail_ * kCommandSize), entry);
    queue.tail_ =
        static_cast<std::uint16_t>((queue.tail_ + 1) % queue.entries_);
    Write32(Doorbell(queue.id_, /*completion=*/false), queue.tail_);
    return command_id;
  }

  // Waits for the next entry on a completion queue and takes it. Nothing
  // comes back if the controller takes longer than Zephyr's NVMe driver
  // would wait.
  std::optional<Completion> WaitForCompletion(QueuePair& queue) {
    for (sc_core::sc_time waited = sc_core::SC_ZERO_TIME;; waited += Pause()) {
      std::array<std::uint8_t, kCompletionSize> entry{};
      ReadMemory(queue.completions_ + (queue.head_ * kCompletionSize), entry);
      const auto status =
          LittleEndian<std::uint16_t>(std::span{entry}.subspan(14));
      // A new entry is one whose phase bit is the one expected.
      if ((status & 1) == (queue.phase_ ? 1 : 0)) {
        queue.head_ = static_cast<std::uint16_t>(queue.head_ + 1);
        if (queue.head_ == queue.entries_) {
          queue.head_ = 0;
          queue.phase_ = !queue.phase_;
        }
        return Completion{
            .command_id =
                LittleEndian<std::uint16_t>(std::span{entry}.subspan(12)),
            .status = static_cast<std::uint16_t>((status >> 1) & 0x7FF),
            .submission_queue_head =
                LittleEndian<std::uint16_t>(std::span{entry}.subspan(8)),
            .result = LittleEndian<std::uint32_t>(entry)};
      }
      if (waited >= Patience()) return std::nullopt;
      bus_.WaitFor(Pause());
    }
  }

  // Reads `blocks` blocks of namespace 1, from block `first` on, with a
  // command on the I/O queue. Returns the data, or nothing if the command
  // fails.
  std::optional<std::vector<std::uint8_t>> ReadBlocks(std::uint64_t first,
                                                      std::uint32_t blocks) {
    std::vector<std::uint8_t> data(blocks * kBlockSize);
    const std::vector<std::uint64_t> pages = ScatteredPages(data.size());
    // Not zeros to begin with, so that data the controller never delivers
    // is not taken for a block of zeros.
    std::ranges::fill(data, std::uint8_t{0xA5});
    CopyToPages(data, pages);
    const auto completion = Transfer(kRead, first, blocks, pages);
    if (!completion || completion->status != 0) return std::nullopt;
    CopyFromPages(pages, data);
    return data;
  }

  // Sends the same read, and returns what the controller said about it
  // in place of the data.
  std::optional<Completion> TryToRead(std::uint64_t first,
                                      std::uint32_t blocks) {
    return TryToRead(first, blocks, ScatteredPages(blocks * kBlockSize));
  }

  // The same read, with the data pages where the caller says they are.
  std::optional<Completion> TryToRead(std::uint64_t first, std::uint32_t blocks,
                                      const std::vector<std::uint64_t>& pages) {
    return Transfer(kRead, first, blocks, pages);
  }

  // Writes whole blocks to namespace 1, from block `first` on. Returns
  // what the controller said.
  std::optional<Completion> WriteBlocks(std::uint64_t first,
                                        std::span<const std::uint8_t> data) {
    const std::vector<std::uint64_t> pages = ScatteredPages(data.size());
    CopyToPages(data, pages);
    return Transfer(kWrite, first,
                    static_cast<std::uint32_t>(data.size() / kBlockSize),
                    pages);
  }

  // Sends a write of `blocks` blocks from the data pages the caller names,
  // and returns what the controller said.
  std::optional<Completion> TryToWrite(
      std::uint64_t first, std::uint32_t blocks,
      const std::vector<std::uint64_t>& pages) {
    return Transfer(kWrite, first, blocks, pages);
  }

  // Asks the controller to make everything written to namespace 1 safe.
  // Returns what it said.
  std::optional<Completion> Flush() {
    return Complete(io_, {.opcode = kFlush, .namespace_id = 1});
  }

  // The Identify command asks the controller to describe itself or what it
  // holds, and gets a 4 KiB page back with each fact at a fixed offset.
  // Each of these returns nothing if the command fails.

  // How many namespaces the controller says it has.
  std::optional<std::uint32_t> NumberOfNamespaces() {
    const auto page = Identify(kDescribeController, 0);
    if (!page) return std::nullopt;
    // NN, 32 bits at byte 516.
    return LittleEndian<std::uint32_t>(std::span{*page}.subspan(516));
  }

  // Sends the Identify for a namespace, and returns what the controller
  // said about it in place of the description.
  std::optional<Completion> TryToIdentifyNamespace(std::uint32_t namespace_id) {
    return Complete(admin_, {.opcode = kIdentify,
                             .namespace_id = namespace_id,
                             .data = Allocate(1),
                             .dword10 = kDescribeNamespace});
  }

  std::optional<Namespace> IdentifyNamespace(std::uint32_t namespace_id) {
    const auto page = Identify(kDescribeNamespace, namespace_id);
    if (!page) return std::nullopt;
    const std::span bytes{*page};
    // The page lists the block formats the namespace could have, 32 bits
    // each from byte 128, and says at byte 26 which one it has (FLBAS, low
    // four bits). A format gives the block size as a power of two, in its
    // bits 23 to 16 (LBADS). NSZE, the size in blocks, is 64 bits at byte 0.
    const std::size_t format = bytes[26] & 0xF;
    const auto block_size_shift =
        (LittleEndian<std::uint32_t>(bytes.subspan(128 + (4 * format))) >> 16) &
        0xFF;
    return Namespace{.blocks = LittleEndian<std::uint64_t>(bytes),
                     .block_size = std::uint32_t{1} << block_size_shift};
  }

  // The identifiers of the namespaces in use, in the order given.
  std::optional<std::vector<std::uint32_t>> ActiveNamespaces() {
    const auto page = Identify(kDescribeActiveNamespaces, 0);
    if (!page) return std::nullopt;
    // 32-bit identifiers, and a zero ends the list.
    std::vector<std::uint32_t> active;
    for (std::size_t offset = 0; offset < page->size(); offset += 4) {
      const auto id =
          LittleEndian<std::uint32_t>(std::span{*page}.subspan(offset));
      if (id == 0) break;
      active.push_back(id);
    }
    return active;
  }

  // Asks for `pairs` I/O queue pairs, with the Set Features command for
  // the Number of Queues feature. Returns how many pairs the controller
  // grants, which may be more or fewer, or nothing if the command fails.
  std::optional<std::uint32_t> AskForIoQueuePairs(std::uint16_t pairs) {
    // Both counts are from zero: submission queues in the low half,
    // completion queues in the high half.
    const auto wanted = static_cast<std::uint32_t>(pairs - 1);
    const std::optional<Completion> completion =
        Complete(admin_, {.opcode = kSetFeatures,
                          .dword10 = kNumberOfQueues,
                          .dword11 = wanted << 16 | wanted});
    if (!completion || completion->status != 0) return std::nullopt;
    return std::min(completion->result & 0xFFFF, completion->result >> 16) + 1;
  }

  // A page of the host's memory that nothing else uses, for a command's
  // data.
  std::uint64_t NewPage() { return Allocate(1); }

  // Tells the controller that the host has dealt with one more of the
  // completions it has taken, by writing the completion queue's head
  // doorbell.
  void Acknowledge(QueuePair& queue) {
    queue.acknowledged_ =
        static_cast<std::uint16_t>((queue.acknowledged_ + 1) % queue.entries_);
    Write32(Doorbell(queue.id_, /*completion=*/true), queue.acknowledged_);
  }

  // Waits until an interrupt line has risen `count` times in all since the
  // start. Returns false if it has not by the time Zephyr's NVMe driver
  // would have given up on a command.
  bool WaitForInterrupts(std::size_t vector, int count) {
    return interrupts_.at(vector)->WaitForRises(count, Patience());
  }

  // How many times the interrupt lines other than `vector` have risen
  // since the start, all together.
  int InterruptsOnOtherLines(std::size_t vector) {
    int rises = 0;
    for (std::size_t other = 0; other < interrupts_.size(); ++other) {
      if (other != vector) rises += interrupts_[other]->Rises();
    }
    return rises;
  }

  // Lets one delta cycle pass: everything else in the platform that is
  // ready gets one turn, and no simulated time goes by. A CPU model does
  // this between two accesses, where this host otherwise makes them back
  // to back.
  void LetADeltaPass() { bus_.WaitFor(sc_core::SC_ZERO_TIME); }

  // Whether an interrupt line is high, once it has had a moment to settle
  // after whatever the host did last.
  bool IsInterrupting(std::size_t vector) {
    bus_.WaitFor(Pause());
    return interrupts_.at(vector)->line->read();
  }

 private:
  // Register offsets, and the bits used in them.
  static constexpr std::uint64_t kCapabilities = 0x00;
  static constexpr std::uint64_t kConfiguration = 0x14;
  static constexpr std::uint32_t kEnable = 1U << 0;
  // CC.IOSQES and CC.IOCQES: commands are 2^6 bytes, completions 2^4.
  static constexpr std::uint32_t kCommandSizes = 6U << 16 | 4U << 20;
  static constexpr std::uint64_t kStatus = 0x1C;
  static constexpr std::uint32_t kReady = 1U << 0;
  static constexpr std::uint64_t kAdminQueueAttributes = 0x24;
  static constexpr std::uint64_t kAdminSubmissionQueue = 0x28;
  static constexpr std::uint64_t kAdminCompletionQueue = 0x30;
  static constexpr std::uint64_t kDoorbells = 0x1000;

  // I/O opcodes.
  static constexpr std::uint8_t kFlush = 0x00;
  static constexpr std::uint8_t kWrite = 0x01;
  static constexpr std::uint8_t kRead = 0x02;
  // The block size the contract asks of a namespace.
  static constexpr std::size_t kBlockSize = 512;
  // Bits of dword 11 in the two commands that create a queue.
  static constexpr std::uint32_t kContiguous = 1U << 0;
  static constexpr std::uint32_t kInterruptsEnabled = 1U << 1;
  // What an Identify command can be asked to describe (its CNS value).
  static constexpr std::uint32_t kDescribeNamespace = 0;
  static constexpr std::uint32_t kDescribeController = 1;
  static constexpr std::uint32_t kDescribeActiveNamespaces = 2;
  // The feature identifier for Number of Queues.
  static constexpr std::uint32_t kNumberOfQueues = 0x07;

  static constexpr std::size_t kCommandSize = 64;
  static constexpr std::size_t kCompletionSize = 16;
  static constexpr std::uint64_t kPageSize = 4096;
  // Short, so that a test can take the queues round their ends with a
  // few commands.
  static constexpr std::uint16_t kQueueEntries = 4;

  // How long the host waits before it looks again. How often a driver
  // polls is up to the driver; a millisecond is short against the limits
  // it waits for.
  static sc_core::sc_time Pause() { return {1, sc_core::SC_MS}; }
  // How long the host waits for the controller to finish a command: as
  // long as Zephyr's NVMe driver does (CONFIG_NVME_REQUEST_TIMEOUT).
  static sc_core::sc_time Patience() { return {5, sc_core::SC_SEC}; }

  // Sends a command, waits for its completion and acknowledges it.
  std::optional<Completion> Complete(QueuePair& queue, const Command& command) {
    Submit(queue, command);
    const std::optional<Completion> completion = WaitForCompletion(queue);
    Acknowledge(queue);
    return completion;
  }

  // Enough pages of the host's memory to hold `bytes`, with a gap after
  // each one. The pages a host can spare for a transfer are rarely next to
  // each other, and a controller must not count on it.
  std::vector<std::uint64_t> ScatteredPages(std::size_t bytes) {
    std::vector<std::uint64_t> pages;
    for (std::size_t held = 0; held < bytes; held += kPageSize) {
      pages.push_back(Allocate(2));
    }
    return pages;
  }

  void CopyToPages(std::span<const std::uint8_t> data,
                   const std::vector<std::uint64_t>& pages) {
    for (std::size_t page = 0; page < pages.size(); ++page) {
      const std::size_t offset = page * kPageSize;
      WriteMemory(pages[page],
                  data.subspan(offset, std::min<std::size_t>(
                                           kPageSize, data.size() - offset)));
    }
  }

  void CopyFromPages(const std::vector<std::uint64_t>& pages,
                     std::span<std::uint8_t> data) {
    for (std::size_t page = 0; page < pages.size(); ++page) {
      const std::size_t offset = page * kPageSize;
      ReadMemory(pages[page],
                 data.subspan(offset, std::min<std::size_t>(
                                          kPageSize, data.size() - offset)));
    }
  }

  // Sends a read or a write of `blocks` blocks on the I/O queue, with the
  // data in `pages`, and returns its completion, acknowledged.
  std::optional<Completion> Transfer(std::uint8_t opcode, std::uint64_t first,
                                     std::uint32_t blocks,
                                     const std::vector<std::uint64_t>& pages) {
    // A command says where its data is page by page. The first page's
    // address goes in the command. The second entry is the second page if
    // there are two pages, and otherwise the address of a page that lists
    // all the pages after the first.
    std::uint64_t more_data = 0;
    if (pages.size() == 2) {
      more_data = pages[1];
    } else if (pages.size() > 2) {
      more_data = Allocate(1);
      for (std::size_t page = 1; page < pages.size(); ++page) {
        std::array<std::uint8_t, 8> entry{};
        Store<std::uint64_t>(pages[page], entry);
        WriteMemory(more_data + ((page - 1) * entry.size()), entry);
      }
    }
    return Complete(io_, {.opcode = opcode,
                          .namespace_id = 1,
                          .data = pages[0],
                          .more_data = more_data,
                          // The starting block in dwords 10 and 11, and the
                          // number of blocks, counted from zero, in dword 12.
                          .dword10 = static_cast<std::uint32_t>(first),
                          .dword11 = static_cast<std::uint32_t>(first >> 32),
                          .dword12 = blocks - 1});
  }

  // Sends an Identify command and returns the page it fills.
  std::optional<std::array<std::uint8_t, kPageSize>> Identify(
      std::uint32_t what, std::uint32_t namespace_id) {
    const std::uint64_t page = Allocate(1);
    const std::optional<Completion> completion =
        Complete(admin_, {.opcode = kIdentify,
                          .namespace_id = namespace_id,
                          .data = page,
                          .dword10 = what});
    if (!completion || completion->status != 0) return std::nullopt;
    std::array<std::uint8_t, kPageSize> bytes{};
    ReadMemory(page, bytes);
    return bytes;
  }

  // Where a queue's doorbell is: submission tail, then completion head,
  // queue after queue. CAP.DSTRD says how far apart they are.
  std::uint64_t Doorbell(std::uint16_t queue, bool completion) {
    const std::uint64_t stride = std::uint64_t{4}
                                 << ((Capabilities() >> 32) & 0xF);
    return kDoorbells +
           (((2 * std::uint64_t{queue}) + (completion ? 1 : 0)) * stride);
  }

  // Waits until CSTS.RDY has the given value, or until the controller's
  // own limit for that has passed (CAP.TO, which counts in 500 ms).
  void WaitUntilReadyIs(bool wanted) {
    const sc_core::sc_time limit =
        static_cast<double>((Capabilities() >> 24) & 0xFF) *
        sc_core::sc_time{500, sc_core::SC_MS};
    for (sc_core::sc_time waited = sc_core::SC_ZERO_TIME;
         IsReady() != wanted && waited < limit; waited += Pause()) {
      bus_.WaitFor(Pause());
    }
  }

  std::uint64_t Capabilities() {
    // A 64-bit register may be read as two halves, low half first.
    return Read32(kCapabilities) | std::uint64_t{Read32(kCapabilities + 4)}
                                       << 32;
  }

  std::uint32_t Read32(std::uint64_t offset) {
    std::array<std::uint8_t, 4> bytes{};
    if (bus_.Read(registers_ + offset, bytes) != tlm::TLM_OK_RESPONSE) {
      ADD_FAILURE() << "Nothing answered a read of the register at offset 0x"
                    << std::hex << offset << ".";
    }
    return LittleEndian<std::uint32_t>(bytes);
  }

  void Write32(std::uint64_t offset, std::uint32_t value) {
    std::array<std::uint8_t, 4> bytes{};
    Store(value, bytes);
    if (bus_.Write(registers_ + offset, bytes) != tlm::TLM_OK_RESPONSE) {
      ADD_FAILURE() << "Nothing took a write to the register at offset 0x"
                    << std::hex << offset << ".";
    }
  }

  // A 64-bit register may be written as two halves, low half first.
  void Write64(std::uint64_t offset, std::uint64_t value) {
    Write32(offset, static_cast<std::uint32_t>(value));
    Write32(offset + 4, static_cast<std::uint32_t>(value >> 32));
  }

  void ReadMemory(std::uint64_t address, std::span<std::uint8_t> data) {
    if (bus_.Read(address, data) != tlm::TLM_OK_RESPONSE) {
      ADD_FAILURE() << "The host has no memory at 0x" << std::hex << address
                    << ".";
    }
  }

  void WriteMemory(std::uint64_t address, std::span<const std::uint8_t> data) {
    if (bus_.Write(address, data) != tlm::TLM_OK_RESPONSE) {
      ADD_FAILURE() << "The host has no memory at 0x" << std::hex << address
                    << ".";
    }
  }

  // Sets aside whole pages of the host's memory, which starts out as zeros.
  std::uint64_t Allocate(std::uint64_t pages) {
    const std::uint64_t address = free_memory_;
    free_memory_ += pages * kPageSize;
    return address;
  }

  template <typename Value>
  static Value LittleEndian(std::span<const std::uint8_t> bytes) {
    Value value = 0;
    for (std::size_t index = 0; index < sizeof(Value); ++index) {
      value |= static_cast<Value>(Value{bytes[index]} << (8 * index));
    }
    return value;
  }

  template <typename Value>
  static void Store(Value value, std::span<std::uint8_t> bytes) {
    for (std::size_t index = 0; index < sizeof(Value); ++index) {
      bytes[index] = static_cast<std::uint8_t>(value >> (8 * index));
    }
  }

  BusDriver& bus_;
  std::uint64_t registers_;
  // The first byte of the host's memory that nothing has been put in yet.
  std::uint64_t free_memory_;
  std::vector<LineWatcher*> interrupts_;
  // One page each is more than they need.
  QueuePair admin_{0, Allocate(1), Allocate(1), kQueueEntries};
  QueuePair io_{1, Allocate(1), Allocate(1), kQueueEntries};
};

#endif  // TESTS_CPP_SUPPORT_NVME_HOST_H_
