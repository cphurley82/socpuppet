#include "socpuppet/core/dma_engine_logic.h"

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

// The engine's registers, each 32 bits wide, as docs/models/dma-engine.md
// gives them.
constexpr std::uint64_t kCommand = 0x00;
constexpr std::uint64_t kStatus = 0x04;
constexpr std::uint64_t kInterruptEnable = 0x08;
constexpr std::uint64_t kHostAddressLow = 0x0C;
constexpr std::uint64_t kHostAddressHigh = 0x10;
constexpr std::uint64_t kLocalAddress = 0x14;
constexpr std::uint64_t kLength = 0x18;

// What can be written to the command register.
constexpr std::uint32_t kFromHost = 1;
constexpr std::uint32_t kToHost = 2;

// The bits of the status register.
constexpr std::uint32_t kDone = 1U << 0;
constexpr std::uint32_t kError = 1U << 1;
constexpr std::uint32_t kBusy = 1U << 2;

// Where the two memories are in these tests, 64 KiB of each. The host's is
// above 4 GiB, so that an address of it needs both halves.
constexpr std::uint64_t kHost = 0x1'0000'0000;
constexpr std::uint64_t kLocal = 0x4000'0000;
constexpr std::size_t kMemorySize = 0x1'0000;

// A memory at some address, on one of the engine's two ports.
class MemoryAt : public MemoryPort {
 public:
  explicit MemoryAt(std::uint64_t base) : base_(base) {}

  bool Read(std::uint64_t address, std::span<std::uint8_t> out) override {
    return address >= base_ && store_.Read(address - base_, out);
  }
  bool Write(std::uint64_t address, std::span<const std::uint8_t> in) override {
    return address >= base_ && store_.Write(address - base_, in);
  }

  // What the memory holds at `address`, `length` bytes of it.
  std::vector<std::uint8_t> At(std::uint64_t address, std::size_t length) {
    std::vector<std::uint8_t> data(length);
    EXPECT_TRUE(Read(address, data));
    return data;
  }

 private:
  std::uint64_t base_;
  MemoryStore store_{kMemorySize};
};

// `length` bytes in which no two neighbours are the same, and which do not
// repeat for a long way.
std::vector<std::uint8_t> SomeBytes(std::size_t length) {
  std::vector<std::uint8_t> data(length);
  for (std::size_t index = 0; index < data.size(); ++index) {
    data[index] = static_cast<std::uint8_t>(1 + index + (index / 251));
  }
  return data;
}

// An engine between a host's memory and the SSD's own, as its CPU sees it.
struct Rig {
  MemoryAt host{kHost};
  MemoryAt local{kLocal};
  DmaEngineLogic engine{host, local};

  bool Write32(std::uint64_t offset, std::uint32_t value) {
    return engine.WriteRegister(offset, LittleEndianBytes(value));
  }
  // The bytes do not start out as zeros, so that a register the engine
  // leaves untouched is not taken for one that reads as zero.
  std::uint32_t Read32(std::uint64_t offset) const {
    std::array<std::uint8_t, 4> bytes{0xA5, 0xA5, 0xA5, 0xA5};
    EXPECT_TRUE(engine.ReadRegister(offset, bytes));
    return LoadLittleEndian<std::uint32_t>(bytes);
  }
  // Says what to move: `length` bytes, between `host_address` and
  // `local_address`.
  void Describe(std::uint64_t host_address, std::uint64_t local_address,
                std::uint32_t length) {
    Write32(kHostAddressLow, static_cast<std::uint32_t>(host_address));
    Write32(kHostAddressHigh, static_cast<std::uint32_t>(host_address >> 32));
    Write32(kLocalAddress, static_cast<std::uint32_t>(local_address));
    Write32(kLength, length);
  }
  // Gives a command and lets the engine carry it out.
  void Do(std::uint32_t command) {
    Write32(kCommand, command);
    engine.CarryOut();
  }
};

}  // namespace

TEST(WhenADmaEngineIsToldToCopyFromTheHost, TheBytesArriveInTheSsdsMemory) {
  Rig rig;
  rig.host.Write(kHost + 0x100, SomeBytes(24));
  rig.Describe(kHost + 0x100, kLocal + 0x200, 24);

  rig.Do(kFromHost);

  EXPECT_EQ(rig.local.At(kLocal + 0x200, 24), SomeBytes(24));
}

TEST(WhenADmaEngineHasCarriedOutACopy, ItsStatusSaysDoneAndNotBusy) {
  for (const std::uint32_t command : {kFromHost, kToHost}) {
    Rig rig;
    rig.Describe(kHost, kLocal, 24);

    rig.Do(command);

    EXPECT_EQ(rig.Read32(kStatus), kDone) << "command " << command;
  }
}

TEST(WhenADmaEngineIsToldToCopyToTheHost, TheBytesArriveInTheHostsMemory) {
  Rig rig;
  rig.local.Write(kLocal + 0x200, SomeBytes(24));
  rig.Describe(kHost + 0x100, kLocal + 0x200, 24);

  rig.Do(kToHost);

  EXPECT_EQ(rig.host.At(kHost + 0x100, 24), SomeBytes(24));
}

// The host's memory is 64 KiB long, and so is the SSD's.
TEST(WhenNothingAnswersAtAnAddressADmaEngineIsToCopyFrom,
     TheStatusSaysErrorAndNothingIsWritten) {
  Rig from_host;
  from_host.local.Write(kLocal, SomeBytes(24));
  from_host.Describe(kHost + kMemorySize, kLocal, 24);
  Rig to_host;
  to_host.host.Write(kHost, SomeBytes(24));
  to_host.Describe(kHost, kLocal + kMemorySize, 24);

  from_host.Do(kFromHost);
  to_host.Do(kToHost);

  EXPECT_EQ(from_host.Read32(kStatus), kError);
  EXPECT_EQ(from_host.local.At(kLocal, 24), SomeBytes(24));
  EXPECT_EQ(to_host.Read32(kStatus), kError);
  EXPECT_EQ(to_host.host.At(kHost, 24), SomeBytes(24));
}

TEST(WhenNothingAnswersAtAnAddressADmaEngineIsToCopyTo, TheStatusSaysError) {
  Rig from_host;
  from_host.Describe(kHost, kLocal + kMemorySize, 24);
  Rig to_host;
  to_host.Describe(kHost + kMemorySize, kLocal, 24);

  from_host.Do(kFromHost);
  to_host.Do(kToHost);

  EXPECT_EQ(from_host.Read32(kStatus), kError);
  EXPECT_EQ(to_host.Read32(kStatus), kError);
}

// A copy of nothing is more likely a mistake in the firmware than something
// it meant, so the engine says so.
TEST(WhenADmaEngineIsToldToCopyNoBytesAtAll, TheStatusSaysError) {
  Rig rig;
  rig.Describe(kHost, kLocal, 0);

  rig.Do(kFromHost);

  EXPECT_EQ(rig.Read32(kStatus), kError);
}

TEST(WhenADmaEngineHasNotYetCarriedOutACommand, ItsStatusSaysBusy) {
  Rig rig;
  rig.Describe(kHost, kLocal, 24);

  rig.Write32(kCommand, kFromHost);

  EXPECT_EQ(rig.Read32(kStatus), kBusy);
}

// The firmware can ask for any length up to 4 GiB, and the engine cannot
// hold that much at once, so it copies a piece at a time. A piece ends
// wherever the engine's own buffer does.
TEST(WhenADmaEngineIsToldToCopyMoreThanItHoldsAtOnce, ItAllArrives) {
  Rig rig;
  rig.host.Write(kHost + 0x10, SomeBytes(10'000));
  rig.Describe(kHost + 0x10, kLocal + 0x20, 10'000);

  rig.Do(kFromHost);

  EXPECT_EQ(rig.local.At(kLocal + 0x20, 10'000), SomeBytes(10'000));
}

// The host's memory ends 16 bytes into this copy's second piece.
TEST(WhenACopyRunsOffTheEndOfWhatAnswers,
     TheStatusSaysErrorAndThePiecesBeforeHaveBeenCopied) {
  Rig rig;
  const std::uint64_t near_the_end = kHost + kMemorySize - 4096 - 16;
  rig.host.Write(near_the_end, SomeBytes(4096));
  rig.Describe(near_the_end, kLocal, 8192);

  rig.Do(kFromHost);

  EXPECT_EQ(rig.Read32(kStatus), kError);
  EXPECT_EQ(rig.local.At(kLocal, 4096), SomeBytes(4096));
}

TEST(WhenADmaEngineIsGivenACommandWhileItIsBusy,
     TheWriteIsRefusedAndTheFirstCommandIsCarriedOutAsItWas) {
  Rig rig;
  rig.host.Write(kHost, SomeBytes(24));
  rig.Describe(kHost, kLocal, 24);
  rig.Write32(kCommand, kFromHost);
  rig.Describe(kHost + 0x100, kLocal, 24);

  EXPECT_FALSE(rig.Write32(kCommand, kToHost));
  rig.engine.CarryOut();

  EXPECT_EQ(rig.local.At(kLocal, 24), SomeBytes(24));
  EXPECT_EQ(rig.host.At(kHost + 0x100, 24), std::vector<std::uint8_t>(24, 0));
}

TEST(WhenADmaEngineIsGivenACommandItDoesNotHave, TheWriteIsRefused) {
  Rig rig;
  rig.Describe(kHost, kLocal, 24);

  EXPECT_FALSE(rig.Write32(kCommand, 0));
  EXPECT_FALSE(rig.Write32(kCommand, 3));
  EXPECT_EQ(rig.Read32(kStatus), 0U);
}

// The registers are the CPU's to write at any time. What a command is
// about is what they said when it was given.
TEST(WhenTheCpuChangesTheRegistersAfterGivingADmaEngineACommand,
     TheCommandIsCarriedOutAsItWasGiven) {
  Rig rig;
  rig.host.Write(kHost + 0x100, SomeBytes(24));
  rig.host.Write(kHost + 0x300, SomeBytes(8));
  rig.Describe(kHost + 0x100, kLocal + 0x200, 24);
  rig.Write32(kCommand, kFromHost);

  rig.Describe(kHost + 0x300, kLocal + 0x400, 8);
  rig.engine.CarryOut();

  EXPECT_EQ(rig.local.At(kLocal + 0x200, 24), SomeBytes(24));
  EXPECT_EQ(rig.local.At(kLocal + 0x400, 8), std::vector<std::uint8_t>(8, 0));
}

TEST(WhenTheCpuReadsBackARegisterItWroteInADmaEngine, ItReadsWhatWasWritten) {
  Rig rig;
  rig.Write32(kInterruptEnable, kDone | kError);
  rig.Write32(kHostAddressLow, 0x1111'1111);
  rig.Write32(kHostAddressHigh, 0x2222'2222);
  rig.Write32(kLocalAddress, 0x3333'3333);
  rig.Write32(kLength, 0x4444'4444);

  EXPECT_EQ(rig.Read32(kInterruptEnable), kDone | kError);
  EXPECT_EQ(rig.Read32(kHostAddressLow), 0x1111'1111U);
  EXPECT_EQ(rig.Read32(kHostAddressHigh), 0x2222'2222U);
  EXPECT_EQ(rig.Read32(kLocalAddress), 0x3333'3333U);
  EXPECT_EQ(rig.Read32(kLength), 0x4444'4444U);
}

// The command register is for writing: there is nothing in it to read.
TEST(WhenTheCpuReadsTheCommandRegisterOfADmaEngine, ItReadsAsZero) {
  Rig rig;
  rig.Write32(kCommand, kFromHost);

  EXPECT_EQ(rig.Read32(kCommand), 0U);
}

TEST(WhenAnAccessToADmaEngineIsNot32BitsWide, ItIsRefused) {
  Rig rig;
  std::array<std::uint8_t, 2> two{1, 0};
  std::array<std::uint8_t, 8> eight{1, 0, 0, 0, 1, 0, 0, 0};

  EXPECT_FALSE(rig.engine.ReadRegister(kStatus, two));
  EXPECT_FALSE(rig.engine.ReadRegister(kStatus, eight));
  EXPECT_FALSE(rig.engine.WriteRegister(kLength, two));
  EXPECT_FALSE(rig.engine.WriteRegister(kLength, eight));
  EXPECT_EQ(rig.Read32(kLength), 0U);
}

// 0x1C is after the last register, and 0x02 is in the middle of one.
TEST(WhenAnAccessToADmaEngineIsBesideItsRegisters, ItIsRefused) {
  Rig rig;
  std::array<std::uint8_t, 4> data{};

  for (const std::uint64_t offset : {0x1CU, 0x02U}) {
    EXPECT_FALSE(rig.engine.ReadRegister(offset, data)) << offset;
    EXPECT_FALSE(rig.engine.WriteRegister(offset, data)) << offset;
  }
}

TEST(WhenACopyIsDoneAndDoneIsEnabledAsAnInterrupt, TheDmaEngineInterrupts) {
  Rig rig;
  rig.Describe(kHost, kLocal, 24);
  rig.Write32(kInterruptEnable, kDone);
  rig.Write32(kCommand, kFromHost);
  const bool while_busy = rig.engine.Interrupting();

  rig.engine.CarryOut();

  EXPECT_FALSE(while_busy);
  EXPECT_TRUE(rig.engine.Interrupting());
}

TEST(WhenTheCpuClearsTheStatusBitThatInterruptedIt,
     TheDmaEngineStopsInterruptingAndTheBitReadsAsClear) {
  Rig rig;
  rig.Describe(kHost, kLocal, 24);
  rig.Write32(kInterruptEnable, kDone);
  rig.Do(kFromHost);

  rig.Write32(kStatus, kDone);

  EXPECT_FALSE(rig.engine.Interrupting());
  EXPECT_EQ(rig.Read32(kStatus), 0U);
}

TEST(WhenADmaEngineHasNothingToDo, CarryingOutSaysSoAndChangesNothing) {
  Rig rig;

  EXPECT_FALSE(rig.engine.CarryOut());
  EXPECT_EQ(rig.Read32(kStatus), 0U);
}

TEST(WhenADmaEngineHasCarriedOutACommand, ThereIsNothingMoreToDo) {
  Rig rig;
  rig.Describe(kHost, kLocal, 24);
  rig.Write32(kCommand, kFromHost);

  EXPECT_TRUE(rig.engine.CarryOut());
  EXPECT_FALSE(rig.engine.CarryOut());
}

}  // namespace socpuppet
