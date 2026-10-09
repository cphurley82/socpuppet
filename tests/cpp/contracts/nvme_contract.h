#ifndef TESTS_CPP_CONTRACTS_NVME_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_NVME_CONTRACT_H_

#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/core/block_store.h"
#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/registry.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/line_watcher.h"
#include "tests/cpp/support/nvme_host.h"
#include "tests/cpp/support/test_components.h"

// The admin completion queue always interrupts on vector 0. An I/O
// completion queue uses whichever vector the host names when it creates
// it, and the tests name this one, so that its interrupts can be told from
// the admin queue's.
constexpr std::size_t kAdminVector = 0;
constexpr std::uint16_t kIoVector = 1;

// What every NVMe function must do, whether it is the behavioral stand-in
// or a whole SSD running firmware. A function is an NVMe controller as its
// PCIe endpoint sees it: a register block, a port for reading and writing
// the host's memory (DMA), and interrupt lines. There is no PCIe here.
//
//   host.driver ─▶ host.bus ─┬─▶ host.memory
//                     ▲      └─▶ the function's registers
//                     └───────── the function's DMA
//   host.irq0, host.irq1 ... ◀── the function's interrupt lines
//
// To hold an implementation to this contract, write a rig for it and
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, NvmeContract,
//                                  ::testing::Types<MyRig>);
// A rig says how to put the function into a platform:
//   static void Register(socpuppet::Registry&);   adds whatever it is made
//       of that the built-in components do not already have
//   static void Add(socpuppet::Platform&);   adds its components, bound to
//       each other, under any names outside the group "host"
//   static const char* Registers();   the port its register block is
//       reached through (a bus target)
//   static const char* Dma();         the port it reaches host memory
//       through (a bus source)
//   static constexpr std::uint64_t kBlocks;   how many 512-byte blocks its
//       one namespace holds
//   static constexpr unsigned kVectors;   how many interrupt lines it has,
//       which must be at least two
//   static std::string Irq(unsigned vector);   the port one of them is
//       driven from (a wire source)
template <typename Rig>
class NvmeContract : public ::testing::Test {
  static_assert(Rig::kVectors > kIoVector,
                "The contract gives its I/O completion queue a vector of "
                "its own, so the function needs at least two.");

 public:
  // Where the host's bus has the function's registers: the controller
  // registers in the first 4 KiB, and the doorbells after them.
  static constexpr std::uint64_t kRegistersBase = 0x1000'0000;
  static constexpr std::uint64_t kRegistersSize = 0x2000;
  // And where it has the host's own memory.
  static constexpr std::uint64_t kMemoryBase = 0x8000'0000;
  static constexpr std::uint64_t kMemorySize = 0x10'0000;

 protected:
  // Builds the platform and runs it with `body` as what the host does. The
  // run ends when the host has done it.
  void OnTheHost(const std::function<void(NvmeHost&)>& body) {
    socpuppet::Registry registry = socpuppet::BuiltinComponents();
    Rig::Register(registry);
    AddBusDriver(registry, "driver", [this, body](BusDriver& bus) {
      NvmeHost host{bus, kRegistersBase, kMemoryBase, InterruptLines()};
      body(host);
      sc_core::sc_pause();
    });
    AddLineWatcher(registry, "line_watcher");
    platform_ = std::make_unique<socpuppet::Platform>(std::move(registry));
    platform_->Add("host.driver", "driver");
    platform_->Add("host.bus", "router",
                   {{"inputs", 2},
                    {"outputs", 2},
                    {"out0.base", kMemoryBase},
                    {"out0.size", kMemorySize},
                    {"out1.base", kRegistersBase},
                    {"out1.size", kRegistersSize}});
    platform_->Add("host.memory", "memory", {{"size", kMemorySize}});
    Rig::Add(*platform_);
    platform_->Bind("host.driver.socket", "host.bus.target");
    platform_->Bind("host.bus.out0", "host.memory.socket");
    platform_->Bind("host.bus.out1", Rig::Registers());
    platform_->Bind(Rig::Dma(), "host.bus.in1");
    for (unsigned vector = 0; vector < Rig::kVectors; ++vector) {
      platform_->Add(Watcher(vector), "line_watcher");
      platform_->Bind(Rig::Irq(vector), Watcher(vector) + ".line");
    }
    platform_->Elaborate();
    platform_->Run();
  }

  std::unique_ptr<socpuppet::Platform> platform_;

 private:
  // The host's end of an interrupt line.
  static std::string Watcher(unsigned vector) {
    return "host.irq" + std::to_string(vector);
  }

  std::vector<LineWatcher*> InterruptLines() {
    std::vector<LineWatcher*> lines;
    lines.reserve(Rig::kVectors);
    for (unsigned vector = 0; vector < Rig::kVectors; ++vector) {
      lines.push_back(
          &platform_->template ModuleAt<LineWatcher>(Watcher(vector)));
    }
    return lines;
  }
};

TYPED_TEST_SUITE_P(NvmeContract);

// One field of a result that may not be there, or nothing if it is not. It
// lets a test compare the field in one step: a missing result then fails
// the comparison like any wrong value.
template <typename Result, typename Field>
std::optional<Field> The(const std::optional<Result>& result,
                         Field Result::* field) {
  if (!result) return std::nullopt;
  return (*result).*field;
}

// The status a completion carries, or nothing if there is no completion.
inline std::optional<std::uint16_t> StatusOf(
    const std::optional<NvmeHost::Completion>& completion) {
  return The(completion, &NvmeHost::Completion::status);
}

// The size of a block, as the contract asks it of a namespace.
constexpr std::size_t kBlockSize = socpuppet::BlockStore::kBlockSize;

// Opcode 3 is one the admin command set does not assign. A command with it
// is the simplest there is: it moves no data and changes nothing.
constexpr std::uint8_t kUnassignedAdminOpcode = 0x03;

TYPED_TEST_P(NvmeContract, AFreshControllerOffersIoQueuesOfAtLeast256Entries) {
  // Zephyr's NVMe driver makes its queues 256 entries long unless it is
  // configured otherwise, and does not ask the controller first.
  std::uint32_t largest_queue = 0;

  this->OnTheHost(
      [&](NvmeHost& host) { largest_queue = host.LargestIoQueueSize(); });

  EXPECT_GE(largest_queue, 256U);
}

TYPED_TEST_P(NvmeContract, WhenTheHostEnablesTheControllerItBecomesReady) {
  bool ready = false;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    ready = host.IsReady();
  });

  EXPECT_TRUE(ready);
}

TYPED_TEST_P(NvmeContract, AnEnabledControllerSaysReadyToADebugAccessToo) {
  bool ready = false;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    ready = host.IsReadyByDebugAccess();
  });

  EXPECT_TRUE(ready);
}

TYPED_TEST_P(NvmeContract, WhenTheHostDisablesTheControllerItStopsBeingReady) {
  bool ready = true;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.Disable();
    ready = host.IsReady();
  });

  EXPECT_FALSE(ready);
}

TYPED_TEST_P(NvmeContract,
             AnAdminCommandWithAnUnknownOpcodeCompletesAsAnInvalidOpcode) {
  std::uint16_t command_id = 0;
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    command_id = host.Submit(host.Admin(), {.opcode = kUnassignedAdminOpcode});
    completion = host.WaitForCompletion(host.Admin());
  });

  EXPECT_EQ(The(completion, &NvmeHost::Completion::command_id), command_id);
  EXPECT_EQ(StatusOf(completion), NvmeHost::kInvalidCommandOpcode);
}

TYPED_TEST_P(NvmeContract, WhenAnAdminCommandCompletesTheAdminLineRises) {
  bool interrupted = false;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.Submit(host.Admin(), {.opcode = kUnassignedAdminOpcode});
    interrupted = host.WaitForInterrupts(kAdminVector, 1);
  });

  EXPECT_TRUE(interrupted);
}

TYPED_TEST_P(NvmeContract,
             WhenTheHostAcknowledgesTheOnlyCompletionTheAdminLineFalls) {
  bool interrupting = true;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.Submit(host.Admin(), {.opcode = kUnassignedAdminOpcode});
    host.WaitForCompletion(host.Admin());
    host.Acknowledge(host.Admin());
    interrupting = host.IsInterrupting(kAdminVector);
  });

  EXPECT_FALSE(interrupting);
}

TYPED_TEST_P(NvmeContract,
             WhenTheHostAcknowledgesOneOfTwoCompletionsTheAdminLineRisesAgain) {
  // A line that simply stayed high would be lost on the way to the host:
  // MSI-X sends a message when the line rises, and Zephyr's driver, having
  // read what it found, acknowledges once and waits for the next message.
  // So the line rises once for the two completions, and a second time
  // after the acknowledgement, for the one still waiting.
  bool interrupted_again = false;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.Submit(host.Admin(), {.opcode = kUnassignedAdminOpcode});
    host.Submit(host.Admin(), {.opcode = kUnassignedAdminOpcode});
    host.WaitForCompletion(host.Admin());
    host.WaitForCompletion(host.Admin());
    host.Acknowledge(host.Admin());
    interrupted_again = host.WaitForInterrupts(kAdminVector, 2);
  });

  EXPECT_TRUE(interrupted_again);
}

TYPED_TEST_P(NvmeContract, ACompletionSaysHowFarTheSubmissionQueueHasBeenRead) {
  std::optional<NvmeHost::Completion> second;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.Submit(host.Admin(), {.opcode = kUnassignedAdminOpcode});
    host.Submit(host.Admin(), {.opcode = kUnassignedAdminOpcode});
    host.WaitForCompletion(host.Admin());
    second = host.WaitForCompletion(host.Admin());
  });

  EXPECT_EQ(The(second, &NvmeHost::Completion::submission_queue_head), 2);
}

TYPED_TEST_P(NvmeContract, WhenTheAdminQueuesWrapAroundCommandsStillComplete) {
  // One command more than the queues have entries. Its command goes into
  // the first slot of the submission queue again, and its completion comes
  // out of the first slot of the completion queue with the phase bit
  // inverted, which is where the host looks for it.
  std::uint16_t last_command_id = 0;
  std::optional<NvmeHost::Completion> last;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    for (std::uint16_t count = 0; count <= host.Admin().Entries(); ++count) {
      last_command_id =
          host.Submit(host.Admin(), {.opcode = kUnassignedAdminOpcode});
      last = host.WaitForCompletion(host.Admin());
      host.Acknowledge(host.Admin());
    }
  });

  EXPECT_EQ(The(last, &NvmeHost::Completion::command_id), last_command_id);
}

TYPED_TEST_P(NvmeContract, AnAdminCompletionRaisesOnlyTheAdminLine) {
  int other_interrupts = -1;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.Submit(host.Admin(), {.opcode = kUnassignedAdminOpcode});
    host.WaitForInterrupts(kAdminVector, 1);
    other_interrupts = host.InterruptsOnOtherLines(kAdminVector);
  });

  EXPECT_EQ(other_interrupts, 0);
}

TYPED_TEST_P(NvmeContract,
             AHostThatComesBackOneDeltaAfterSubmittingStillReadsReady) {
  // A host may come back one delta cycle later, at the same simulated
  // time, when the controller may or may not have started on the command.
  bool ready = false;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.Submit(host.Admin(), {.opcode = kUnassignedAdminOpcode});
    host.LetADeltaPass();
    ready = host.IsReady();
  });

  EXPECT_TRUE(ready);
}

TYPED_TEST_P(NvmeContract,
             AnAcknowledgementOneDeltaAfterASubmissionLosesNoInterrupt) {
  // The host acknowledges the first completion one delta cycle after it
  // submits a second command, when the controller may or may not have
  // started on it. Either way the line must be seen to fall, and then to
  // rise for the second completion.
  bool interrupted_again = false;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.Submit(host.Admin(), {.opcode = kUnassignedAdminOpcode});
    host.WaitForCompletion(host.Admin());
    host.Submit(host.Admin(), {.opcode = kUnassignedAdminOpcode});
    host.LetADeltaPass();
    host.Acknowledge(host.Admin());
    interrupted_again = host.WaitForInterrupts(kAdminVector, 2);
  });

  EXPECT_TRUE(interrupted_again);
}

TYPED_TEST_P(NvmeContract, TheControllerSaysItHasOneNamespace) {
  std::optional<std::uint32_t> namespaces;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    namespaces = host.NumberOfNamespaces();
  });

  EXPECT_EQ(namespaces, 1U);
}

TYPED_TEST_P(NvmeContract, NamespaceOneSaysHowManyBlocksItHolds) {
  std::optional<NvmeHost::Namespace> name_space;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    name_space = host.IdentifyNamespace(1);
  });

  EXPECT_EQ(The(name_space, &NvmeHost::Namespace::blocks), TypeParam::kBlocks);
}

TYPED_TEST_P(NvmeContract, NamespaceOneHas512ByteBlocks) {
  std::optional<NvmeHost::Namespace> name_space;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    name_space = host.IdentifyNamespace(1);
  });

  EXPECT_EQ(The(name_space, &NvmeHost::Namespace::block_size), 512U);
}

TYPED_TEST_P(NvmeContract, TheListOfActiveNamespacesHoldsNamespaceOneAlone) {
  std::optional<std::vector<std::uint32_t>> active;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    active = host.ActiveNamespaces();
  });

  EXPECT_EQ(active, std::vector<std::uint32_t>{1});
}

TYPED_TEST_P(NvmeContract, WhenTheHostAsksForAnIoQueuePairItIsGrantedOne) {
  std::optional<std::uint32_t> granted;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    granted = host.AskForIoQueuePairs(1);
  });

  // A controller may grant more than it was asked for.
  EXPECT_GE(granted.value_or(0), 1U);
}

TYPED_TEST_P(NvmeContract,
             AnIdentifyForSomethingItCannotDescribeIsAnInvalidField) {
  // Identify says what it wants described with a number (CNS). This one is
  // from the range the specification keeps in reserve.
  constexpr std::uint32_t kNothingToDescribe = 0xFF;
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.Submit(host.Admin(), {.opcode = NvmeHost::kIdentify,
                               .data = host.NewPage(),
                               .dword10 = kNothingToDescribe});
    completion = host.WaitForCompletion(host.Admin());
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kInvalidField);
}

TYPED_TEST_P(NvmeContract,
             AnIdentifyForANamespaceThatDoesNotExistIsAnInvalidNamespace) {
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    completion = host.TryToIdentifyNamespace(2);
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kInvalidNamespace);
}

TYPED_TEST_P(NvmeContract,
             SettingAFeatureTheControllerDoesNotHaveIsAnInvalidField) {
  // Feature identifier 0 is one the specification keeps in reserve.
  constexpr std::uint32_t kNoSuchFeature = 0x00;
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.Submit(host.Admin(),
                {.opcode = NvmeHost::kSetFeatures, .dword10 = kNoSuchFeature});
    completion = host.WaitForCompletion(host.Admin());
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kInvalidField);
}

TYPED_TEST_P(NvmeContract, TheHostCanCreateAnIoQueuePair) {
  bool created = false;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    created = host.CreateIoQueues(kIoVector);
  });

  EXPECT_TRUE(created);
}

TYPED_TEST_P(
    NvmeContract,
    ACompletionQueueTheControllerHasNoRoomForIsAnInvalidQueueIdentifier) {
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    // I/O queues are numbered from 1, so the first identifier the
    // controller does not have is one more than the number it grants.
    const std::uint32_t granted = host.AskForIoQueuePairs(1).value_or(0);
    completion = host.CreateIoCompletionQueue(
        static_cast<std::uint16_t>(granted + 1), host.NewPage(), kIoVector);
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kInvalidQueueIdentifier);
}

TYPED_TEST_P(
    NvmeContract,
    ASubmissionQueueCreatedBeforeItsCompletionQueueIsCompletionQueueInvalid) {
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    completion = host.CreateIoSubmissionQueue(1, host.NewPage(),
                                              /*completion_queue=*/1);
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kCompletionQueueInvalid);
}

TYPED_TEST_P(NvmeContract,
             CreatingACompletionQueueThatExistsIsAnInvalidQueueIdentifier) {
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoCompletionQueue(1, host.NewPage(), kIoVector);
    completion = host.CreateIoCompletionQueue(1, host.NewPage(), kIoVector);
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kInvalidQueueIdentifier);
}

TYPED_TEST_P(NvmeContract,
             CreatingASubmissionQueueThatExistsIsAnInvalidQueueIdentifier) {
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    completion = host.CreateIoSubmissionQueue(1, host.NewPage(),
                                              /*completion_queue=*/1);
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kInvalidQueueIdentifier);
}

// A queue is a ring with one slot always left empty, so that a full queue
// and an empty one do not look alike. A ring of one entry could hold
// nothing.
TYPED_TEST_P(NvmeContract, ACompletionQueueOfOneEntryIsAnInvalidQueueSize) {
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    completion = host.CreateIoCompletionQueue(1, host.NewPage(), kIoVector,
                                              /*entries=*/1);
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kInvalidQueueSize);
}

TYPED_TEST_P(NvmeContract, ASubmissionQueueOfOneEntryIsAnInvalidQueueSize) {
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoCompletionQueue(1, host.NewPage(), kIoVector);
    completion = host.CreateIoSubmissionQueue(
        1, host.NewPage(), /*completion_queue=*/1, /*entries=*/1);
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kInvalidQueueSize);
}

TYPED_TEST_P(NvmeContract, AReadOfANamespaceThatDoesNotExistIsRefused) {
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    completion = host.TryToReadNamespace(2);
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kInvalidNamespace);
}

TYPED_TEST_P(NvmeContract, AWriteToANamespaceThatDoesNotExistIsRefused) {
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    completion = host.TryToWriteNamespace(2);
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kInvalidNamespace);
}

// Fills the I/O completion queue: sends flushes and takes their
// completions without acknowledging any, until the queue has no room. A
// queue is full with one slot to spare.
inline void FillTheIoCompletionQueue(NvmeHost& host) {
  const int room = host.Io().Entries() - 1;
  for (int taken = 0; taken < room; ++taken) {
    host.SubmitFlush();
    host.WaitForCompletion(host.Io());
  }
}

TYPED_TEST_P(NvmeContract,
             ACommandIsNotCompletedWhileItsCompletionQueueIsFull) {
  bool completed = true;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    FillTheIoCompletionQueue(host);
    host.SubmitFlush();
    completed = host.HasACompletion(host.Io());
  });

  EXPECT_FALSE(completed);
}

TYPED_TEST_P(NvmeContract,
             ACommandThatWaitedForRoomCompletesOnceTheHostAcknowledges) {
  std::uint16_t waiting = 0;
  std::optional<std::uint16_t> completed;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    FillTheIoCompletionQueue(host);
    waiting = host.SubmitFlush();
    host.Acknowledge(host.Io());
    if (const auto completion = host.WaitForCompletion(host.Io())) {
      completed = completion->command_id;
    }
  });

  EXPECT_EQ(completed, waiting);
}

TYPED_TEST_P(NvmeContract, ABlockThatWasNeverWrittenReadsAsZeros) {
  std::optional<std::vector<std::uint8_t>> block;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    block = host.ReadBlocks(/*first=*/0, /*blocks=*/1);
  });

  EXPECT_EQ(block, std::vector<std::uint8_t>(kBlockSize, 0));
}

TYPED_TEST_P(NvmeContract,
             WhenAnIoCommandCompletesTheLineOfItsQueuesVectorRises) {
  bool interrupted = false;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    host.ReadBlocks(/*first=*/0, /*blocks=*/1);
    interrupted = host.WaitForInterrupts(kIoVector, 1);
  });

  EXPECT_TRUE(interrupted);
}

// Bytes to write to a drive: no two neighbours the same, and no block the
// same as the next.
inline std::vector<std::uint8_t> SomeData(std::size_t size) {
  std::vector<std::uint8_t> data(size);
  for (std::size_t index = 0; index < size; ++index) {
    data[index] = static_cast<std::uint8_t>((index * 7) + (index / kBlockSize));
  }
  return data;
}

TYPED_TEST_P(NvmeContract, ABlockReadsBackAsItWasWritten) {
  const std::vector<std::uint8_t> written = SomeData(kBlockSize);
  std::optional<std::vector<std::uint8_t>> read_back;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    host.WriteBlocks(/*first=*/3, written);
    read_back = host.ReadBlocks(/*first=*/3, /*blocks=*/1);
  });

  EXPECT_EQ(read_back, written);
}

// A drive that only remembered the last thing it was given would pass a
// test that reads back what it has just written.
TYPED_TEST_P(NvmeContract,
             ABlockIsStillAsWrittenAfterOneFarFromItHasBeenWrittenToo) {
  const std::vector<std::uint8_t> first_written = SomeData(kBlockSize);
  const std::vector<std::uint8_t> last_written(kBlockSize, 0x5A);
  std::optional<std::vector<std::uint8_t>> first_read_back;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    host.WriteBlocks(/*first=*/0, first_written);
    host.WriteBlocks(/*first=*/TypeParam::kBlocks - 1, last_written);
    first_read_back = host.ReadBlocks(/*first=*/0, /*blocks=*/1);
  });

  EXPECT_EQ(first_read_back, first_written);
}

TYPED_TEST_P(NvmeContract, ATransferOfTwoPagesReadsBackAsItWasWritten) {
  // Two pages of memory is sixteen blocks. The command gives the address
  // of each page.
  const std::vector<std::uint8_t> written = SomeData(16 * kBlockSize);
  std::optional<std::vector<std::uint8_t>> read_back;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    host.WriteBlocks(/*first=*/0, written);
    read_back = host.ReadBlocks(/*first=*/0, /*blocks=*/16);
  });

  EXPECT_EQ(read_back, written);
}

TYPED_TEST_P(NvmeContract, ATransferOfThreePagesReadsBackAsItWasWritten) {
  // With more than two pages, the command carries the address of a list of
  // the pages after the first.
  const std::vector<std::uint8_t> written = SomeData(24 * kBlockSize);
  std::optional<std::vector<std::uint8_t>> read_back;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    host.WriteBlocks(/*first=*/0, written);
    read_back = host.ReadBlocks(/*first=*/0, /*blocks=*/24);
  });

  EXPECT_EQ(read_back, written);
}

TYPED_TEST_P(NvmeContract, AReadPastTheEndOfTheNamespaceIsOutOfRange) {
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    // The last block, and one that is not there.
    completion = host.TryToRead(/*first=*/TypeParam::kBlocks - 1,
                                /*blocks=*/2);
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kLbaOutOfRange);
}

TYPED_TEST_P(NvmeContract,
             AReadWhoseDataPageIsWhereNothingAnswersIsADataTransferError) {
  // Just past the host's memory, where the bus has nothing mapped.
  const std::uint64_t nowhere = this->kMemoryBase + this->kMemorySize;
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    completion = host.TryToRead(/*first=*/0, /*blocks=*/1, /*pages=*/{nowhere});
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kDataTransferError);
}

TYPED_TEST_P(NvmeContract,
             AWriteWhoseDataPageIsWhereNothingAnswersIsADataTransferError) {
  const std::uint64_t nowhere = this->kMemoryBase + this->kMemorySize;
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    completion =
        host.TryToWrite(/*first=*/0, /*blocks=*/1, /*pages=*/{nowhere});
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kDataTransferError);
}

TYPED_TEST_P(NvmeContract,
             AWritePastTheEndOfTheNamespaceIsOutOfRangeAndWritesNothing) {
  std::optional<NvmeHost::Completion> completion;
  std::optional<std::vector<std::uint8_t>> last_block;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    completion = host.WriteBlocks(/*first=*/TypeParam::kBlocks - 1,
                                  SomeData(2 * kBlockSize));
    last_block = host.ReadBlocks(/*first=*/TypeParam::kBlocks - 1,
                                 /*blocks=*/1);
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kLbaOutOfRange);
  EXPECT_EQ(last_block, std::vector<std::uint8_t>(kBlockSize, 0));
}

TYPED_TEST_P(NvmeContract, WhatWasWrittenIsStillThereAfterAControllerReset) {
  // Disabling the controller resets it, and a driver does that before it
  // enables one it has just found. The drive's contents are not part of
  // what is reset.
  const std::vector<std::uint8_t> written = SomeData(kBlockSize);
  std::optional<std::vector<std::uint8_t>> read_back;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    host.WriteBlocks(/*first=*/0, written);
    host.Disable();
    host.Enable();
    host.CreateIoQueues(kIoVector);
    read_back = host.ReadBlocks(/*first=*/0, /*blocks=*/1);
  });

  EXPECT_EQ(read_back, written);
}

TYPED_TEST_P(NvmeContract, AControllerResetDoesAwayWithTheIoQueues) {
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    host.Disable();
    host.Enable();
    // Completion queue 1 was there before the reset. A submission queue
    // can only be created for a completion queue that exists.
    completion = host.CreateIoSubmissionQueue(1, host.NewPage(),
                                              /*completion_queue=*/1);
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kCompletionQueueInvalid);
}

TYPED_TEST_P(NvmeContract, AfterAControllerResetTheAdminQueuesStartOver) {
  // The host starts again at the first slot of fresh queues, and so must
  // the controller, or the two would be looking at different slots.
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.Submit(host.Admin(), {.opcode = kUnassignedAdminOpcode});
    host.WaitForCompletion(host.Admin());
    host.Disable();
    host.Enable();
    host.Submit(host.Admin(), {.opcode = kUnassignedAdminOpcode});
    completion = host.WaitForCompletion(host.Admin());
  });

  EXPECT_TRUE(completion.has_value());
}

TYPED_TEST_P(NvmeContract, AFlushSucceeds) {
  // Flush asks for everything written so far to be made safe. A driver
  // sends one when a file system asks it to sync.
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    completion = host.Flush();
  });

  EXPECT_EQ(StatusOf(completion), 0);
}

TYPED_TEST_P(NvmeContract, AReadFarPastTheEndOfTheNamespaceIsOutOfRange) {
  // A block number so large that it would wrap around if it were turned
  // into a byte offset.
  constexpr std::uint64_t kFarAway = std::uint64_t{1} << 55;
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    completion = host.TryToRead(/*first=*/kFarAway, /*blocks=*/1);
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kLbaOutOfRange);
}

TYPED_TEST_P(NvmeContract,
             AnIoCommandWithAnUnknownOpcodeCompletesAsAnInvalidOpcode) {
  // Opcode 3 is one the NVM command set does not assign either.
  constexpr std::uint8_t kUnassignedIoOpcode = 0x03;
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    host.Submit(host.Io(), {.opcode = kUnassignedIoOpcode, .namespace_id = 1});
    completion = host.WaitForCompletion(host.Io());
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kInvalidCommandOpcode);
}

TYPED_TEST_P(NvmeContract,
             CreatingCompletionQueueZeroIsAnInvalidQueueIdentifier) {
  // Queue 0 is the admin queue, which the registers set up.
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    completion = host.CreateIoCompletionQueue(0, host.NewPage(), kIoVector);
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kInvalidQueueIdentifier);
}

TYPED_TEST_P(
    NvmeContract,
    ASubmissionQueueTheControllerHasNoRoomForIsAnInvalidQueueIdentifier) {
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    const std::optional<std::uint32_t> granted = host.AskForIoQueuePairs(1);
    if (!granted) return;
    // Completion queue 1 has to exist, or its absence is what gets
    // reported.
    host.CreateIoQueues(kIoVector);
    completion = host.CreateIoSubmissionQueue(
        static_cast<std::uint16_t>(*granted + 1), host.NewPage(),
        /*completion_queue=*/1);
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kInvalidQueueIdentifier);
}

TYPED_TEST_P(NvmeContract,
             CreatingSubmissionQueueZeroIsAnInvalidQueueIdentifier) {
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    host.CreateIoQueues(kIoVector);
    completion = host.CreateIoSubmissionQueue(0, host.NewPage(),
                                              /*completion_queue=*/1);
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kInvalidQueueIdentifier);
}

TYPED_TEST_P(NvmeContract,
             ACompletionQueueOnAVectorTheFunctionLacksIsAnInvalidVector) {
  std::optional<NvmeHost::Completion> completion;

  this->OnTheHost([&](NvmeHost& host) {
    host.Enable();
    // Vectors are numbered from zero, so the first one the function does
    // not have is its number of vectors.
    completion = host.CreateIoCompletionQueue(1, host.NewPage(),
                                              /*vector=*/TypeParam::kVectors);
  });

  EXPECT_EQ(StatusOf(completion), NvmeHost::kInvalidInterruptVector);
}

REGISTER_TYPED_TEST_SUITE_P(
    NvmeContract, AFreshControllerOffersIoQueuesOfAtLeast256Entries,
    WhenTheHostEnablesTheControllerItBecomesReady,
    AnEnabledControllerSaysReadyToADebugAccessToo,
    WhenTheHostDisablesTheControllerItStopsBeingReady,
    AnAdminCommandWithAnUnknownOpcodeCompletesAsAnInvalidOpcode,
    WhenAnAdminCommandCompletesTheAdminLineRises,
    WhenTheHostAcknowledgesTheOnlyCompletionTheAdminLineFalls,
    WhenTheHostAcknowledgesOneOfTwoCompletionsTheAdminLineRisesAgain,
    ACompletionSaysHowFarTheSubmissionQueueHasBeenRead,
    WhenTheAdminQueuesWrapAroundCommandsStillComplete,
    AnAdminCompletionRaisesOnlyTheAdminLine,
    AHostThatComesBackOneDeltaAfterSubmittingStillReadsReady,
    AnAcknowledgementOneDeltaAfterASubmissionLosesNoInterrupt,
    TheControllerSaysItHasOneNamespace, NamespaceOneSaysHowManyBlocksItHolds,
    NamespaceOneHas512ByteBlocks,
    TheListOfActiveNamespacesHoldsNamespaceOneAlone,
    WhenTheHostAsksForAnIoQueuePairItIsGrantedOne,
    AnIdentifyForSomethingItCannotDescribeIsAnInvalidField,
    AnIdentifyForANamespaceThatDoesNotExistIsAnInvalidNamespace,
    SettingAFeatureTheControllerDoesNotHaveIsAnInvalidField,
    TheHostCanCreateAnIoQueuePair,
    ACompletionQueueTheControllerHasNoRoomForIsAnInvalidQueueIdentifier,
    ASubmissionQueueCreatedBeforeItsCompletionQueueIsCompletionQueueInvalid,
    ABlockThatWasNeverWrittenReadsAsZeros,
    WhenAnIoCommandCompletesTheLineOfItsQueuesVectorRises,
    ABlockReadsBackAsItWasWritten,
    ABlockIsStillAsWrittenAfterOneFarFromItHasBeenWrittenToo,
    ATransferOfTwoPagesReadsBackAsItWasWritten,
    ATransferOfThreePagesReadsBackAsItWasWritten,
    AReadPastTheEndOfTheNamespaceIsOutOfRange,
    AReadWhoseDataPageIsWhereNothingAnswersIsADataTransferError,
    AWriteWhoseDataPageIsWhereNothingAnswersIsADataTransferError,
    AWritePastTheEndOfTheNamespaceIsOutOfRangeAndWritesNothing,
    WhatWasWrittenIsStillThereAfterAControllerReset,
    AControllerResetDoesAwayWithTheIoQueues,
    AfterAControllerResetTheAdminQueuesStartOver, AFlushSucceeds,
    AReadFarPastTheEndOfTheNamespaceIsOutOfRange,
    AnIoCommandWithAnUnknownOpcodeCompletesAsAnInvalidOpcode,
    CreatingCompletionQueueZeroIsAnInvalidQueueIdentifier,
    ASubmissionQueueTheControllerHasNoRoomForIsAnInvalidQueueIdentifier,
    CreatingSubmissionQueueZeroIsAnInvalidQueueIdentifier,
    ACompletionQueueOnAVectorTheFunctionLacksIsAnInvalidVector,
    CreatingACompletionQueueThatExistsIsAnInvalidQueueIdentifier,
    CreatingASubmissionQueueThatExistsIsAnInvalidQueueIdentifier,
    ACompletionQueueOfOneEntryIsAnInvalidQueueSize,
    ASubmissionQueueOfOneEntryIsAnInvalidQueueSize,
    AReadOfANamespaceThatDoesNotExistIsRefused,
    AWriteToANamespaceThatDoesNotExistIsRefused,
    ACommandIsNotCompletedWhileItsCompletionQueueIsFull,
    ACommandThatWaitedForRoomCompletesOnceTheHostAcknowledges);

#endif  // TESTS_CPP_CONTRACTS_NVME_CONTRACT_H_
