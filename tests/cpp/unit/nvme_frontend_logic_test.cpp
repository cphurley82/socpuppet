#include "socpuppet/core/nvme_frontend_logic.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <ostream>
#include <span>
#include <vector>

#include <gtest/gtest.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/memory_port.h"
#include "socpuppet/core/memory_store.h"

namespace socpuppet {

namespace {

// The registers the host sees, as the NVMe specification gives them. The
// doorbells follow the controller registers, 32 bits each, in pairs: a
// submission queue's tail, then the completion queue's head.
enum HostRegister : std::uint64_t {
  kCap = 0x00,
  kCc = 0x14,
  kCsts = 0x1C,
  kAqa = 0x24,
  kAsq = 0x28,
  kAcq = 0x30,
  kDoorbells = 0x1000,
};

// The registers the SSD's CPU sees, as docs/models/nvme-frontend.md gives
// them. Each is 32 bits wide, and the command is 64 bytes.
enum CpuRegister : std::uint64_t {
  kStatus = 0x00,
  kInterruptEnable = 0x04,
  kControl = 0x08,
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

// The bits of the CPU's status register.
enum StatusBit : std::uint32_t {
  // The host has enabled the controller, or disabled it. Each stays set
  // until the CPU writes a one to it.
  kEnabled = 1U << 0,
  kDisabled = 1U << 1,
  // A command is waiting for the CPU. It is set for as long as one is.
  kCommandWaiting = 1U << 2,
};

// The bit of the control register by which firmware says it is ready.
constexpr std::uint32_t kReady = 1U << 0;

// Where the host of these tests keeps its admin queues, and the first pair
// of I/O queues it asks for. Every queue has four entries.
constexpr std::uint64_t kAdminSubmissionQueue = 0x1000;
constexpr std::uint64_t kAdminCompletionQueue = 0x2000;
constexpr std::uint64_t kIoSubmissionQueue = 0x3000;
constexpr std::uint64_t kIoCompletionQueue = 0x4000;
constexpr std::uint16_t kLastSlot = 3;

// What is written to the queue-create register.
enum QueueKind : std::uint32_t {
  kCompletionQueue = 1,
  kSubmissionQueue = 2,
};

// How long a command is, and where in it the host puts the identifier it
// gives the command.
constexpr std::size_t kCommandBytes = 64;
constexpr std::size_t kCommandIdOffset = 2;

// A command with an identifier, and otherwise bytes that are all different
// and that differ from another command's.
std::vector<std::uint8_t> SomeCommand(std::uint16_t command_id) {
  std::vector<std::uint8_t> command(kCommandBytes);
  for (std::size_t index = 0; index < command.size(); ++index) {
    command[index] = static_cast<std::uint8_t>(index + (7 * command_id) + 1);
  }
  StoreLittleEndian(command_id, std::span{command}.subspan(kCommandIdOffset));
  return command;
}

// What a completion says, as the host reads it out of a completion queue:
// 16 bytes, laid out as the NVMe specification gives them.
struct Completion {
  // The command's answer, where it has one that fits in 32 bits.
  std::uint32_t result = 0;
  // Which queue the command was submitted to, how far the controller has
  // read that queue, and the identifier the host gave the command.
  std::uint16_t submission_queue = 0;
  std::uint16_t submission_head = 0;
  std::uint16_t command_id = 0;
  // The bit that tells a new completion from the one that was in the slot
  // a lap of the queue ago.
  bool phase = false;
  // The status code, zero for success, and which list of codes it is from.
  std::uint8_t status = 0;
  std::uint8_t status_type = 0;

  bool operator==(const Completion&) const = default;
};

void PrintTo(const Completion& completion, std::ostream* out) {
  *out << "{result " << completion.result << ", from queue "
       << completion.submission_queue << " read up to "
       << completion.submission_head << ", command " << completion.command_id
       << ", phase " << completion.phase << ", status "
       << int{completion.status} << " of type " << int{completion.status_type}
       << "}";
}

// The host's memory: 64 KiB of it, at address 0.
class HostMemory : public MemoryPort {
 public:
  bool Read(std::uint64_t address, std::span<std::uint8_t> out) override {
    return store_.Read(address, out);
  }
  bool Write(std::uint64_t address, std::span<const std::uint8_t> in) override {
    return store_.Write(address, in);
  }

 private:
  MemoryStore store_{0x1'0000};
};

// A frontend with two interrupt vectors, between a host and the SSD's CPU.
struct Rig {
  HostMemory memory;
  NvmeFrontendLogic frontend{memory, /*vectors=*/2};
  // Where the host will put its next command in each submission queue.
  std::array<std::uint16_t, 2> tails{};

  // A register as the host reads it. The bytes do not start out as zeros,
  // so that a register the frontend leaves untouched is not taken for one
  // that reads as zero.
  std::uint64_t HostRead64(std::uint64_t offset) const {
    std::array<std::uint8_t, 8> bytes{0xA5, 0xA5, 0xA5, 0xA5,
                                      0xA5, 0xA5, 0xA5, 0xA5};
    EXPECT_TRUE(frontend.ReadHostRegister(offset, bytes));
    return LoadLittleEndian<std::uint64_t>(bytes);
  }
  std::uint32_t HostRead32(std::uint64_t offset) const {
    std::array<std::uint8_t, 4> bytes{0xA5, 0xA5, 0xA5, 0xA5};
    EXPECT_TRUE(frontend.ReadHostRegister(offset, bytes));
    return LoadLittleEndian<std::uint32_t>(bytes);
  }
  bool HostWrite32(std::uint64_t offset, std::uint32_t value) {
    return frontend.WriteHostRegister(offset, LittleEndianBytes(value));
  }
  bool HostWrite64(std::uint64_t offset, std::uint64_t value) {
    return frontend.WriteHostRegister(offset, LittleEndianBytes(value));
  }

  // What a host does to enable the controller, and to disable it: it says
  // where its admin queues are, of four entries each, and sets CC.EN, or
  // clears it.
  void HostEnables() {
    HostWrite32(kAqa, 3U << 16 | 3U);
    HostWrite64(kAsq, kAdminSubmissionQueue);
    HostWrite64(kAcq, kAdminCompletionQueue);
    HostWrite32(kCc, 1);
  }
  void HostDisables() { HostWrite32(kCc, 0); }

  // A register as the SSD's CPU reads it, and a write by the CPU.
  std::uint32_t CpuRead32(std::uint64_t offset) const {
    std::array<std::uint8_t, 4> bytes{0xA5, 0xA5, 0xA5, 0xA5};
    EXPECT_TRUE(frontend.ReadCpuRegister(offset, bytes));
    return LoadLittleEndian<std::uint32_t>(bytes);
  }
  bool CpuWrite32(std::uint64_t offset, std::uint32_t value) {
    return frontend.WriteCpuRegister(offset, LittleEndianBytes(value));
  }

  // What a host does to submit a command: it writes the command into the
  // queue's next slot, and the new tail to the queue's doorbell. To its
  // admin queue, or to its first I/O queue.
  bool HostSubmits(const std::vector<std::uint8_t>& command) {
    return SubmitTo(0, kAdminSubmissionQueue, command);
  }
  bool HostSubmitsIo(const std::vector<std::uint8_t>& command) {
    return SubmitTo(1, kIoSubmissionQueue, command);
  }
  bool SubmitTo(std::size_t queue_id, std::uint64_t queue,
                const std::vector<std::uint8_t>& command) {
    std::uint16_t& tail = tails[queue_id];
    memory.Write(queue + (tail * kCommandBytes), command);
    tail = static_cast<std::uint16_t>((tail + 1) % (kLastSlot + 1));
    return HostWrite32(kDoorbells + (8 * queue_id), tail);
  }

  // What firmware does when it has agreed to create a queue: it says which
  // queue, where it is and how long, and what goes with it. For a
  // completion queue that is its interrupt vector, and for a submission
  // queue the completion queue its commands' completions go to.
  bool CpuCreates(QueueKind kind, std::uint32_t queue_id, std::uint64_t base,
                  std::uint32_t link) {
    CpuWrite32(kQueueId, queue_id);
    CpuWrite32(kQueueBaseLow, static_cast<std::uint32_t>(base));
    CpuWrite32(kQueueBaseHigh, static_cast<std::uint32_t>(base >> 32));
    CpuWrite32(kQueueLast, kLastSlot);
    CpuWrite32(kQueueLink, link);
    return CpuWrite32(kQueueCreate, kind);
  }
  // The first pair of I/O queues, with the second interrupt vector.
  void CpuCreatesIoQueues() {
    CpuCreates(kCompletionQueue, 1, kIoCompletionQueue, /*vector=*/1);
    CpuCreates(kSubmissionQueue, 1, kIoSubmissionQueue, /*completion queue=*/1);
  }

  // The command that is waiting for the CPU, as the CPU reads it.
  std::vector<std::uint8_t> CommandWaiting() const {
    std::vector<std::uint8_t> command(kCommandBytes, 0xA5);
    EXPECT_TRUE(frontend.ReadCpuRegister(kCommand, command));
    return command;
  }

  // What the CPU does when it has dealt with the waiting command: it says
  // what the completion is to say, and has it posted. The status is the
  // code in its low byte, and which list the code is from above that.
  bool CpuPosts(std::uint32_t status = 0, std::uint32_t result = 0) {
    CpuWrite32(kCompletionResult, result);
    CpuWrite32(kCompletionStatus, status);
    return CpuWrite32(kCompletionPost, 1);
  }

  // What the host finds in a slot of a completion queue.
  Completion HostReadsCompletion(std::uint64_t queue, std::size_t slot) {
    std::array<std::uint8_t, 16> bytes{};
    EXPECT_TRUE(memory.Read(queue + (slot * bytes.size()), bytes));
    const std::span<const std::uint8_t> entry{bytes};
    const auto phase_and_status =
        LoadLittleEndian<std::uint16_t>(entry.subspan(14));
    return {
        .result = LoadLittleEndian<std::uint32_t>(entry),
        .submission_queue = LoadLittleEndian<std::uint16_t>(entry.subspan(10)),
        .submission_head = LoadLittleEndian<std::uint16_t>(entry.subspan(8)),
        .command_id = LoadLittleEndian<std::uint16_t>(entry.subspan(12)),
        .phase = (phase_and_status & 1U) != 0,
        .status = static_cast<std::uint8_t>(phase_and_status >> 1),
        .status_type =
            static_cast<std::uint8_t>((phase_and_status >> 9) & 0x7)};
  }

  // Whether the host sees the controller as ready: CSTS.RDY.
  bool HostSeesReady() const { return (HostRead32(kCsts) & 1U) != 0; }
};

}  // namespace

// The host waits for the controller to become ready after enabling it, and
// CAP.TO says for how long at most, in units of 500 ms. A controller with
// firmware needs the wait: the firmware may still be starting.
TEST(WhenTheHostReadsWhatAnNvmeFrontendCanDo,
     ItIsToldToWaitUpToASecondForReady) {
  const Rig rig;

  const std::uint64_t ready_timeout = (rig.HostRead64(kCap) >> 24) & 0xFF;

  EXPECT_EQ(ready_timeout, 2U);
}

// On a controller with no firmware, enabling it is all there is to being
// ready. Here the firmware has work to do first, and says when it is done.
TEST(WhenTheHostEnablesAnNvmeFrontend, ItIsNotReadyUntilItsFirmwareSaysSo) {
  Rig rig;

  rig.HostEnables();

  EXPECT_FALSE(rig.HostSeesReady());
}

TEST(WhenTheFirmwareOfAnNvmeFrontendSaysItIsReady, TheHostSeesReady) {
  Rig rig;
  rig.HostEnables();

  rig.CpuWrite32(kControl, kReady);

  EXPECT_TRUE(rig.HostSeesReady());
}

TEST(WhenTheFirmwareOfAnNvmeFrontendSaysItIsNoLongerReady,
     TheHostSeesNotReady) {
  Rig rig;
  rig.HostEnables();
  rig.CpuWrite32(kControl, kReady);

  rig.CpuWrite32(kControl, 0);

  EXPECT_FALSE(rig.HostSeesReady());
}

TEST(WhenTheHostEnablesAnNvmeFrontend, ItsCpuIsToldSo) {
  Rig rig;

  rig.HostEnables();

  EXPECT_EQ(rig.CpuRead32(kStatus), kEnabled);
}

TEST(WhenTheHostDisablesAnNvmeFrontend, ItsCpuIsToldSo) {
  Rig rig;
  rig.HostEnables();
  rig.CpuWrite32(kStatus, kEnabled);

  rig.HostDisables();

  EXPECT_EQ(rig.CpuRead32(kStatus), kDisabled);
}

// A host that disables the controller and enables it again before the
// firmware has looked leaves both for it to find.
TEST(WhenTheCpuAcknowledgesOneOfTwoThingsTheHostHasDone,
     TheOtherIsStillThereToRead) {
  Rig rig;
  rig.HostEnables();
  rig.HostDisables();

  rig.CpuWrite32(kStatus, kDisabled);

  EXPECT_EQ(rig.CpuRead32(kStatus), kEnabled);
}

TEST(WhenTheHostSubmitsACommandToAnNvmeFrontend, ItsCpuFindsItWaiting) {
  Rig rig;
  rig.HostEnables();
  rig.CpuWrite32(kStatus, kEnabled);

  rig.HostSubmits(SomeCommand(7));
  rig.frontend.Step();

  EXPECT_EQ(rig.CpuRead32(kStatus), kCommandWaiting);
  EXPECT_EQ(rig.CommandWaiting(), SomeCommand(7));
}

// The frontend holds one command for the CPU at a time.
TEST(WhenACommandIsWaitingForTheCpuOfAnNvmeFrontend, TheNextIsNotFetched) {
  Rig rig;
  rig.HostEnables();
  rig.HostSubmits(SomeCommand(7));
  rig.HostSubmits(SomeCommand(8));
  rig.frontend.Step();

  EXPECT_FALSE(rig.frontend.Step());

  EXPECT_EQ(rig.CommandWaiting(), SomeCommand(7));
}

// It is not something the host did, to be acknowledged: it says how
// things are, and stops saying so when the command has been dealt with.
TEST(WhenTheCpuWritesAOneToTheCommandWaitingBitOfAnNvmeFrontend,
     TheCommandIsStillWaiting) {
  Rig rig;
  rig.HostEnables();
  rig.CpuWrite32(kStatus, kEnabled);
  rig.HostSubmits(SomeCommand(7));
  rig.frontend.Step();

  rig.CpuWrite32(kStatus, kCommandWaiting);

  EXPECT_EQ(rig.CpuRead32(kStatus), kCommandWaiting);
}

TEST(WhenNoCommandIsWaitingForTheCpuOfAnNvmeFrontend, TheCommandReadsAsZeros) {
  const Rig rig;

  EXPECT_EQ(rig.CommandWaiting(), std::vector<std::uint8_t>(kCommandBytes, 0));
}

TEST(WhenACommandFromTheAdminQueueIsWaiting, TheCpuIsToldItCameFromQueueZero) {
  Rig rig;
  rig.HostEnables();
  rig.HostSubmits(SomeCommand(7));
  rig.frontend.Step();

  EXPECT_EQ(rig.CpuRead32(kCommandQueue), 0U);
}

// The completion says which command it is for and where it came from,
// which the frontend knows, and how it went, which only the firmware does.
TEST(WhenTheCpuPostsTheCompletionOfTheWaitingCommand,
     TheHostFindsItInTheCompletionQueue) {
  Rig rig;
  rig.HostEnables();
  rig.HostSubmits(SomeCommand(7));
  rig.frontend.Step();

  rig.CpuPosts(/*status=*/0x02, /*result=*/0x1234'5678);
  rig.frontend.Step();

  EXPECT_EQ(rig.HostReadsCompletion(kAdminCompletionQueue, 0),
            (Completion{.result = 0x1234'5678,
                        .submission_queue = 0,
                        .submission_head = 1,
                        .command_id = 7,
                        .phase = true,
                        .status = 0x02,
                        .status_type = 0}));
}

// NVMe has a list of status codes that mean the same for every command,
// and each command has a list of its own. Type 1 is the command's own.
TEST(WhenTheCpuPostsAStatusFromTheCommandsOwnList,
     TheCompletionSaysWhichListItIsFrom) {
  Rig rig;
  rig.HostEnables();
  rig.HostSubmits(SomeCommand(7));
  rig.frontend.Step();

  rig.CpuPosts(/*status=*/1U << 8 | 0x01);
  rig.frontend.Step();

  const Completion posted = rig.HostReadsCompletion(kAdminCompletionQueue, 0);
  EXPECT_EQ(posted.status, 0x01);
  EXPECT_EQ(posted.status_type, 1);
}

// The frontend writes to the host's memory in its own time, and not inside
// the CPU's write. But the command stops waiting at once: the CPU has
// dealt with it, and must not be told about it again.
TEST(WhenTheCpuHasJustAskedForACompletionToBePosted,
     TheCommandNoLongerWaitsAndNothingIsInTheHostsMemoryYet) {
  Rig rig;
  rig.HostEnables();
  rig.CpuWrite32(kStatus, kEnabled);
  rig.HostSubmits(SomeCommand(7));
  rig.frontend.Step();

  rig.CpuPosts();

  EXPECT_EQ(rig.CpuRead32(kStatus), 0U);
  EXPECT_EQ(rig.HostReadsCompletion(kAdminCompletionQueue, 0), Completion{});
}

TEST(WhenAnNvmeFrontendHasPostedACompletion, ItFetchesTheNextCommand) {
  Rig rig;
  rig.HostEnables();
  rig.HostSubmits(SomeCommand(7));
  rig.HostSubmits(SomeCommand(8));
  rig.frontend.Step();
  rig.CpuPosts();

  rig.frontend.Step();

  EXPECT_EQ(rig.CommandWaiting(), SomeCommand(8));
}

TEST(WhenTheCpuAsksForACompletionWithNoCommandWaiting, TheWriteIsRefused) {
  Rig rig;
  rig.HostEnables();

  EXPECT_FALSE(rig.CpuPosts());
}

TEST(WhenTheCpuAsksTwiceForTheCompletionOfOneCommand, TheSecondIsRefused) {
  Rig rig;
  rig.HostEnables();
  rig.HostSubmits(SomeCommand(7));
  rig.frontend.Step();
  rig.CpuPosts();

  EXPECT_FALSE(rig.CpuPosts());
}

// The frontend is asking for the host's attention while a completion queue
// holds something the host has not acknowledged, on the queue's vector.
// The admin queue's is the first.
TEST(WhenAnNvmeFrontendHasPostedACompletion, ItInterruptsTheHost) {
  Rig rig;
  rig.HostEnables();
  rig.HostSubmits(SomeCommand(7));
  rig.frontend.Step();
  const bool before = rig.frontend.HostInterrupts().Interrupting(0);
  rig.CpuPosts();

  rig.frontend.Step();

  EXPECT_FALSE(before);
  EXPECT_TRUE(rig.frontend.HostInterrupts().Interrupting(0));
  EXPECT_FALSE(rig.frontend.HostInterrupts().Interrupting(1));
}

// The host asks for a queue with an admin command, and the firmware decides
// whether it may have one. If so it tells the frontend, which from then on
// takes that queue's doorbell and fetches from it.
TEST(WhenFirmwareHasAnNvmeFrontendCreateAPairOfIoQueues,
     AHostsCommandOnThemReachesTheCpuAndItsCompletionTheHost) {
  Rig rig;
  rig.HostEnables();
  rig.CpuCreatesIoQueues();

  const bool rang = rig.HostSubmitsIo(SomeCommand(9));
  rig.frontend.Step();
  const std::vector<std::uint8_t> waiting = rig.CommandWaiting();
  const std::uint32_t from_queue = rig.CpuRead32(kCommandQueue);
  rig.CpuPosts();
  rig.frontend.Step();

  EXPECT_TRUE(rang);
  EXPECT_EQ(waiting, SomeCommand(9));
  EXPECT_EQ(from_queue, 1U);
  EXPECT_EQ(rig.HostReadsCompletion(kIoCompletionQueue, 0),
            (Completion{.submission_queue = 1,
                        .submission_head = 1,
                        .command_id = 9,
                        .phase = true}));
}

TEST(WhenAnNvmeFrontendHasPostedACompletionToAnIoQueue,
     ItInterruptsTheHostOnThatQueuesVector) {
  Rig rig;
  rig.HostEnables();
  rig.CpuCreatesIoQueues();
  rig.HostSubmitsIo(SomeCommand(9));
  rig.frontend.Step();
  rig.CpuPosts();

  rig.frontend.Step();

  EXPECT_TRUE(rig.frontend.HostInterrupts().Interrupting(1));
  EXPECT_FALSE(rig.frontend.HostInterrupts().Interrupting(0));
}

// Firmware checks what the host asks for before it has a queue created, so
// these are the firmware's own mistakes. The frontend still refuses what
// it could not carry out: the host's memory is not its to guess at.
TEST(WhenFirmwareHasAnNvmeFrontendCreateAQueueItCannotHave, TheWriteIsRefused) {
  Rig rig;
  rig.HostEnables();
  rig.CpuCreatesIoQueues();

  // The admin queues are the frontend's own, and there are eight I/O
  // queues of each kind.
  EXPECT_FALSE(rig.CpuCreates(kCompletionQueue, 0, 0x5000, 1));
  EXPECT_FALSE(rig.CpuCreates(kSubmissionQueue, 0, 0x5000, 1));
  EXPECT_FALSE(rig.CpuCreates(kCompletionQueue, 9, 0x5000, 1));
  EXPECT_FALSE(rig.CpuCreates(kSubmissionQueue, 9, 0x5000, 1));
  // A queue that exists.
  EXPECT_FALSE(rig.CpuCreates(kCompletionQueue, 1, 0x5000, 1));
  EXPECT_FALSE(rig.CpuCreates(kSubmissionQueue, 1, 0x5000, 1));
  // A submission queue whose completions would have nowhere to go.
  EXPECT_FALSE(rig.CpuCreates(kSubmissionQueue, 2, 0x5000, 2));
  // A completion queue on an interrupt vector the frontend has no line
  // for: it has two.
  EXPECT_FALSE(rig.CpuCreates(kCompletionQueue, 2, 0x5000, 2));
  // A kind of queue there is not.
  EXPECT_FALSE(rig.CpuCreates(QueueKind{0}, 2, 0x5000, 1));
  EXPECT_FALSE(rig.CpuCreates(QueueKind{3}, 2, 0x5000, 1));
}

// A queue's last slot is a 16-bit number, as its size is in the command
// that asks for it.
TEST(WhenFirmwareHasAnNvmeFrontendCreateAQueueLongerThanAQueueCanBe,
     TheWriteIsRefused) {
  Rig rig;
  rig.HostEnables();
  rig.CpuWrite32(kQueueId, 1);
  rig.CpuWrite32(kQueueLast, 0x1'0000);
  rig.CpuWrite32(kQueueLink, 1);

  EXPECT_FALSE(rig.CpuWrite32(kQueueCreate, kCompletionQueue));
}

// How many I/O queue pairs it has is in the low half, and how many
// interrupt vectors in the high half. The host asks the firmware both, and
// this is where the firmware finds out.
TEST(WhenFirmwareAsksAnNvmeFrontendWhatItHas,
     ItSaysEightIoQueuePairsAndItsVectors) {
  const Rig rig;

  EXPECT_EQ(rig.CpuRead32(kLimits), 2U << 16 | 8U);
}

}  // namespace socpuppet
