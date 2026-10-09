#include "socpuppet/core/nvme_frontend_logic.h"

#include <array>
#include <cstddef>
#include <cstdint>
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

// Where the host of these tests keeps its admin queues.
constexpr std::uint64_t kAdminSubmissionQueue = 0x1000;
constexpr std::uint64_t kAdminCompletionQueue = 0x2000;

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
  // Where the host will put its next admin command.
  std::uint16_t admin_tail = 0;

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

  // What a host does to submit a command to its admin queue: it writes the
  // command into the queue's next slot, and the new tail to the doorbell.
  void HostSubmits(const std::vector<std::uint8_t>& command) {
    memory.Write(kAdminSubmissionQueue + (admin_tail * kCommandBytes), command);
    admin_tail = static_cast<std::uint16_t>((admin_tail + 1) % 4);
    HostWrite32(kDoorbells, admin_tail);
  }

  // The command that is waiting for the CPU, as the CPU reads it.
  std::vector<std::uint8_t> CommandWaiting() const {
    std::vector<std::uint8_t> command(kCommandBytes, 0xA5);
    EXPECT_TRUE(frontend.ReadCpuRegister(kCommand, command));
    return command;
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

}  // namespace socpuppet
