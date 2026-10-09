#include "socpuppet/core/flash_controller_logic.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <vector>

#include <gtest/gtest.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/memory_port.h"
#include "socpuppet/core/memory_store.h"
#include "socpuppet/core/nand_array.h"
#include "socpuppet/core/nand_port.h"

namespace socpuppet {

namespace {

// The controller's registers, each 32 bits wide, as
// docs/models/flash-controller.md gives them.
constexpr std::uint64_t kCommand = 0x00;
constexpr std::uint64_t kStatus = 0x04;
constexpr std::uint64_t kInterruptEnable = 0x08;
constexpr std::uint64_t kBlock = 0x0C;
constexpr std::uint64_t kPage = 0x10;
constexpr std::uint64_t kLocalAddress = 0x14;
constexpr std::uint64_t kPageSizeRegister = 0x20;
constexpr std::uint64_t kPagesPerBlockRegister = 0x24;
constexpr std::uint64_t kBlocksRegister = 0x28;

// What can be written to the command register.
constexpr std::uint32_t kReadPage = 1;
constexpr std::uint32_t kProgramPage = 2;
constexpr std::uint32_t kEraseBlock = 3;
constexpr std::uint32_t kIdentify = 4;

// The bits of the status register.
constexpr std::uint32_t kDone = 1U << 0;
constexpr std::uint32_t kError = 1U << 1;
constexpr std::uint32_t kBusy = 1U << 2;

// A small chip: 4 blocks of 8 pages, each page 16 bytes.
constexpr NandGeometry kSmall{
    .page_size = 16, .pages_per_block = 8, .blocks = 4};
// One past the end of that chip.
constexpr std::uint32_t kNoSuchBlock = 4;

// A chip on the controller's NAND port.
class Chip : public NandPort {
 public:
  NandArray array{kSmall};

  std::optional<NandGeometry> Geometry() override { return array.Geometry(); }
  bool ReadPage(std::uint32_t block, std::uint32_t page,
                std::span<std::uint8_t> out) override {
    return array.ReadPage(block, page, out) == NandResult::kDone;
  }
  bool ProgramPage(std::uint32_t block, std::uint32_t page,
                   std::span<const std::uint8_t> in) override {
    return array.ProgramPage(block, page, in) == NandResult::kDone;
  }
  bool EraseBlock(std::uint32_t block) override {
    return array.EraseBlock(block) == NandResult::kDone;
  }

  // What the chip holds in one page.
  std::vector<std::uint8_t> PageAt(std::uint32_t block,
                                   std::uint32_t page) const {
    std::vector<std::uint8_t> data(kSmall.page_size);
    EXPECT_EQ(array.ReadPage(block, page, data), NandResult::kDone);
    return data;
  }
};

// Nothing on the controller's NAND port, or a chip that answers nothing.
class NoChip : public NandPort {
 public:
  std::optional<NandGeometry> Geometry() override { return std::nullopt; }
  bool ReadPage(std::uint32_t, std::uint32_t,
                std::span<std::uint8_t>) override {
    return false;
  }
  bool ProgramPage(std::uint32_t, std::uint32_t,
                   std::span<const std::uint8_t>) override {
    return false;
  }
  bool EraseBlock(std::uint32_t) override { return false; }
};

// The SSD's own memory: 256 bytes of it, at address 0.
class Buffer : public MemoryPort {
 public:
  MemoryStore store{256};

  bool Read(std::uint64_t address, std::span<std::uint8_t> out) override {
    return store.Read(address, out);
  }
  bool Write(std::uint64_t address, std::span<const std::uint8_t> in) override {
    return store.Write(address, in);
  }

  // What the memory holds at `address`, a page's worth.
  std::vector<std::uint8_t> PageAt(std::uint64_t address) const {
    std::vector<std::uint8_t> data(kSmall.page_size);
    EXPECT_TRUE(store.Read(address, data));
    return data;
  }
};

// A page of data in which no two neighbouring bytes are the same.
std::vector<std::uint8_t> SomePage(std::uint8_t first_byte = 1) {
  std::vector<std::uint8_t> data(kSmall.page_size);
  for (std::size_t index = 0; index < data.size(); ++index) {
    data[index] = static_cast<std::uint8_t>(first_byte + index);
  }
  return data;
}

// A controller with a chip and a buffer, as its CPU sees it, before it
// has been told anything.
template <typename ChipType>
struct RigWith {
  ChipType chip;
  Buffer buffer;
  FlashControllerLogic controller{chip, buffer};

  bool Write32(std::uint64_t offset, std::uint32_t value) {
    return controller.WriteRegister(offset, LittleEndianBytes(value));
  }
  // The bytes do not start out as zeros, so that a register the controller
  // leaves untouched is not taken for one that reads as zero.
  std::uint32_t Read32(std::uint64_t offset) const {
    std::array<std::uint8_t, 4> bytes{0xA5, 0xA5, 0xA5, 0xA5};
    EXPECT_TRUE(controller.ReadRegister(offset, bytes));
    return LoadLittleEndian<std::uint32_t>(bytes);
  }
  // Gives a command and lets the controller carry it out.
  void Do(std::uint32_t command) {
    Write32(kCommand, command);
    controller.CarryOut();
  }
};

// The same, once its firmware has started it: the chip has been
// identified, and the status that said so has been cleared.
struct Rig : RigWith<Chip> {
  Rig() {
    Do(kIdentify);
    Write32(kStatus, kDone);
  }
};

}  // namespace

TEST(WhenAFlashControllerIsToldToReadAPage, ThePageArrivesInLocalMemory) {
  Rig rig;
  rig.chip.array.ProgramPage(2, 5, SomePage());
  rig.Write32(kBlock, 2);
  rig.Write32(kPage, 5);
  rig.Write32(kLocalAddress, 0x40);

  rig.Write32(kCommand, kReadPage);
  rig.controller.CarryOut();

  EXPECT_EQ(rig.buffer.PageAt(0x40), SomePage());
}

TEST(WhenAFlashControllerHasNotYetCarriedOutACommand,
     ItsStatusSaysBusyAndNotDone) {
  Rig rig;

  rig.Write32(kCommand, kReadPage);

  EXPECT_EQ(rig.Read32(kStatus) & (kBusy | kDone), kBusy);
}

TEST(WhenAFlashControllerHasCarriedOutACommand, ItsStatusSaysDoneAndNotBusy) {
  for (const std::uint32_t command :
       {kReadPage, kProgramPage, kEraseBlock, kIdentify}) {
    Rig rig;

    rig.Do(command);

    EXPECT_EQ(rig.Read32(kStatus), kDone) << "command " << command;
  }
}

TEST(WhenAFlashControllerIsToldToProgramAPage,
     TheChipsPageHoldsWhatLocalMemoryHeld) {
  Rig rig;
  rig.buffer.store.Write(0x40, SomePage());
  rig.Write32(kBlock, 2);
  rig.Write32(kPage, 5);
  rig.Write32(kLocalAddress, 0x40);

  rig.Write32(kCommand, kProgramPage);
  rig.controller.CarryOut();

  EXPECT_EQ(rig.chip.PageAt(2, 5), SomePage());
}

TEST(WhenAFlashControllerIsToldToEraseABlock, TheBlocksPagesReadAsAllOnes) {
  Rig rig;
  rig.chip.array.ProgramPage(2, 5, SomePage());
  rig.Write32(kBlock, 2);

  rig.Write32(kCommand, kEraseBlock);
  rig.controller.CarryOut();

  EXPECT_EQ(rig.chip.PageAt(2, 5),
            std::vector<std::uint8_t>(kSmall.page_size, 0xFF));
}

TEST(WhenTheChipRefusesWhatAFlashControllerAsksOfIt,
     TheStatusSaysErrorAndNotDone) {
  for (const std::uint32_t command : {kReadPage, kProgramPage, kEraseBlock}) {
    Rig rig;
    rig.Write32(kBlock, kNoSuchBlock);

    rig.Write32(kCommand, command);
    rig.controller.CarryOut();

    EXPECT_EQ(rig.Read32(kStatus), kError) << "command " << command;
  }
}

// The buffer is 256 bytes long, so nothing answers at 0x1000.
TEST(WhenLocalMemoryDoesNotTakeThePageAFlashControllerRead,
     TheStatusSaysErrorAndNotDone) {
  Rig rig;
  rig.Write32(kLocalAddress, 0x1000);

  rig.Write32(kCommand, kReadPage);
  rig.controller.CarryOut();

  EXPECT_EQ(rig.Read32(kStatus), kError);
}

TEST(WhenLocalMemoryDoesNotGiveThePageAFlashControllerIsToProgram,
     TheStatusSaysErrorAndTheChipIsLeftAlone) {
  Rig rig;
  rig.Write32(kLocalAddress, 0x1000);

  rig.Write32(kCommand, kProgramPage);
  rig.controller.CarryOut();

  EXPECT_EQ(rig.Read32(kStatus), kError);
  EXPECT_EQ(rig.chip.PageAt(0, 0),
            std::vector<std::uint8_t>(kSmall.page_size, 0xFF));
}

TEST(WhenAFlashControllerIsGivenACommandWhileItIsBusy,
     TheWriteIsRefusedAndTheFirstCommandIsCarriedOutAsItWas) {
  Rig rig;
  rig.chip.array.ProgramPage(2, 5, SomePage());
  rig.Write32(kBlock, 2);
  rig.Write32(kPage, 5);
  rig.Write32(kLocalAddress, 0x40);
  rig.Write32(kCommand, kReadPage);

  EXPECT_FALSE(rig.Write32(kCommand, kEraseBlock));
  rig.controller.CarryOut();

  EXPECT_EQ(rig.buffer.PageAt(0x40), SomePage());
  EXPECT_EQ(rig.chip.PageAt(2, 5), SomePage());
}

TEST(WhenAFlashControllerIsGivenACommandItDoesNotHave, TheWriteIsRefused) {
  Rig rig;

  EXPECT_FALSE(rig.Write32(kCommand, 0));
  EXPECT_FALSE(rig.Write32(kCommand, 5));
  EXPECT_EQ(rig.Read32(kStatus), 0U);
}

TEST(WhenOneIsWrittenToAStatusBitOfAFlashController, TheBitIsCleared) {
  Rig done;
  done.Write32(kCommand, kReadPage);
  done.controller.CarryOut();
  Rig error;
  error.Write32(kBlock, kNoSuchBlock);
  error.Write32(kCommand, kReadPage);
  error.controller.CarryOut();

  done.Write32(kStatus, kDone);
  error.Write32(kStatus, kError);

  EXPECT_EQ(done.Read32(kStatus), 0U);
  EXPECT_EQ(error.Read32(kStatus), 0U);
}

TEST(WhenZeroIsWrittenToAStatusBitOfAFlashController, TheBitStaysAsItWas) {
  Rig rig;
  rig.Write32(kCommand, kReadPage);
  rig.controller.CarryOut();

  rig.Write32(kStatus, kError);

  EXPECT_EQ(rig.Read32(kStatus), kDone);
}

// Busy is the controller's to say, and not the CPU's to take back.
TEST(WhenOneIsWrittenToTheBusyBitOfAFlashController, ItStaysBusy) {
  Rig rig;
  rig.Write32(kCommand, kReadPage);

  rig.Write32(kStatus, kBusy);

  EXPECT_EQ(rig.Read32(kStatus), kBusy);
}

// So that what the status says is always about the last command, with no
// need to clear it first.
TEST(WhenAFlashControllerIsGivenANewCommand,
     WhatTheStatusSaidOfTheLastOneIsGone) {
  Rig rig;
  rig.Write32(kBlock, kNoSuchBlock);
  rig.Write32(kCommand, kReadPage);
  rig.controller.CarryOut();
  rig.Write32(kBlock, 0);

  rig.Write32(kCommand, kReadPage);

  EXPECT_EQ(rig.Read32(kStatus), kBusy);
}

TEST(WhenACommandIsDoneAndDoneIsEnabledAsAnInterrupt,
     TheFlashControllerInterrupts) {
  Rig rig;
  rig.Write32(kInterruptEnable, kDone);
  rig.Write32(kCommand, kReadPage);
  const bool while_busy = rig.controller.Interrupting();

  rig.controller.CarryOut();

  EXPECT_FALSE(while_busy);
  EXPECT_TRUE(rig.controller.Interrupting());
}

TEST(WhenACommandIsDoneAndNoInterruptIsEnabled,
     TheFlashControllerDoesNotInterrupt) {
  Rig rig;
  rig.Write32(kCommand, kReadPage);

  rig.controller.CarryOut();

  EXPECT_FALSE(rig.controller.Interrupting());
}

TEST(WhenACommandFailsAndOnlyDoneIsEnabledAsAnInterrupt,
     TheFlashControllerDoesNotInterrupt) {
  Rig rig;
  rig.Write32(kInterruptEnable, kDone);
  rig.Write32(kBlock, kNoSuchBlock);
  rig.Write32(kCommand, kReadPage);

  rig.controller.CarryOut();

  EXPECT_FALSE(rig.controller.Interrupting());
}

TEST(WhenTheCpuClearsTheStatusBitThatInterruptedIt,
     TheFlashControllerStopsInterrupting) {
  Rig rig;
  rig.Write32(kInterruptEnable, kDone);
  rig.Write32(kCommand, kReadPage);
  rig.controller.CarryOut();

  rig.Write32(kStatus, kDone);

  EXPECT_FALSE(rig.controller.Interrupting());
}

TEST(WhenAFlashControllerHasBeenToldToIdentifyTheChip,
     ItsGeometryRegistersSayWhatTheChipSays) {
  RigWith<Chip> rig;

  rig.Do(kIdentify);

  EXPECT_EQ(rig.Read32(kStatus), kDone);

  EXPECT_EQ(rig.Read32(kPageSizeRegister), 16U);
  EXPECT_EQ(rig.Read32(kPagesPerBlockRegister), 8U);
  EXPECT_EQ(rig.Read32(kBlocksRegister), 4U);
}

TEST(WhenTheCpuReadsBackARegisterItWroteInAFlashController,
     ItReadsWhatWasWritten) {
  Rig rig;
  rig.Write32(kInterruptEnable, kDone | kError);
  rig.Write32(kBlock, 0x1111'1111);
  rig.Write32(kPage, 0x2222'2222);
  rig.Write32(kLocalAddress, 0x3333'3333);

  EXPECT_EQ(rig.Read32(kInterruptEnable), kDone | kError);
  EXPECT_EQ(rig.Read32(kBlock), 0x1111'1111U);
  EXPECT_EQ(rig.Read32(kPage), 0x2222'2222U);
  EXPECT_EQ(rig.Read32(kLocalAddress), 0x3333'3333U);
}

// Only the status bits can interrupt, so only they can be enabled.
TEST(WhenTheCpuEnablesInterruptsAFlashControllerDoesNotHave,
     TheRegisterReadsBackWithoutThem) {
  Rig rig;

  rig.Write32(kInterruptEnable, 0xFFFF'FFFF);

  EXPECT_EQ(rig.Read32(kInterruptEnable), kDone | kError);
}

// The command register is for writing: there is nothing in it to read.
TEST(WhenTheCpuReadsTheCommandRegisterOfAFlashController, ItReadsAsZero) {
  Rig rig;
  rig.Write32(kCommand, kReadPage);

  EXPECT_EQ(rig.Read32(kCommand), 0U);
}

TEST(WhenAnAccessToAFlashControllerIsNot32BitsWide, ItIsRefused) {
  Rig rig;
  std::array<std::uint8_t, 2> two{1, 0};
  std::array<std::uint8_t, 8> eight{1, 0, 0, 0, 1, 0, 0, 0};

  EXPECT_FALSE(rig.controller.ReadRegister(kStatus, two));
  EXPECT_FALSE(rig.controller.ReadRegister(kStatus, eight));
  EXPECT_FALSE(rig.controller.WriteRegister(kBlock, two));
  EXPECT_FALSE(rig.controller.WriteRegister(kBlock, eight));
  EXPECT_EQ(rig.Read32(kBlock), 0U);
}

// 0x18 is between two registers, 0x2C is after the last, and 0x02 is in
// the middle of one.
TEST(WhenAnAccessToAFlashControllerIsBesideItsRegisters, ItIsRefused) {
  Rig rig;
  std::array<std::uint8_t, 4> data{};

  for (const std::uint64_t offset : {0x18U, 0x2CU, 0x02U}) {
    EXPECT_FALSE(rig.controller.ReadRegister(offset, data)) << offset;
    EXPECT_FALSE(rig.controller.WriteRegister(offset, data)) << offset;
  }
}

// What the chip is cannot be changed by writing to a register.
TEST(WhenTheCpuWritesToAGeometryRegisterOfAFlashController, ItIsRefused) {
  Rig rig;

  EXPECT_FALSE(rig.Write32(kPageSizeRegister, 32));
  EXPECT_FALSE(rig.Write32(kPagesPerBlockRegister, 32));
  EXPECT_FALSE(rig.Write32(kBlocksRegister, 32));
}

TEST(WhenAFlashControllerHasNothingToDo, CarryingOutSaysSoAndChangesNothing) {
  Rig rig;

  EXPECT_FALSE(rig.controller.CarryOut());
  EXPECT_EQ(rig.Read32(kStatus), 0U);
}

TEST(WhenAFlashControllerHasCarriedOutACommand, ThereIsNothingMoreToDo) {
  Rig rig;
  rig.Write32(kCommand, kReadPage);

  EXPECT_TRUE(rig.controller.CarryOut());
  EXPECT_FALSE(rig.controller.CarryOut());
}

TEST(WhenTheChipWillNotSayWhatItIs,
     IdentifyingItEndsInErrorAndTheGeometryRegistersReadAsZero) {
  RigWith<NoChip> rig;

  rig.Do(kIdentify);

  EXPECT_EQ(rig.Read32(kStatus), kError);
  EXPECT_EQ(rig.Read32(kPageSizeRegister), 0U);
  EXPECT_EQ(rig.Read32(kPagesPerBlockRegister), 0U);
  EXPECT_EQ(rig.Read32(kBlocksRegister), 0U);
}

// The controller cannot move a page before it knows how big a page is.
TEST(WhenAFlashControllerHasNotIdentifiedTheChip,
     ItsGeometryRegistersReadAsZero) {
  RigWith<Chip> rig;

  EXPECT_EQ(rig.Read32(kPageSizeRegister), 0U);
  EXPECT_EQ(rig.Read32(kPagesPerBlockRegister), 0U);
  EXPECT_EQ(rig.Read32(kBlocksRegister), 0U);
}

TEST(WhenAFlashControllerHasNotIdentifiedTheChip,
     ACommandForAPageEndsInErrorAndMovesNothing) {
  RigWith<Chip> rig;
  rig.chip.array.ProgramPage(0, 0, SomePage());
  rig.buffer.store.Write(0x40, SomePage(50));
  rig.Write32(kLocalAddress, 0x40);

  rig.Do(kReadPage);
  const std::uint32_t after_the_read = rig.Read32(kStatus);
  rig.Do(kProgramPage);

  EXPECT_EQ(after_the_read, kError);
  EXPECT_EQ(rig.Read32(kStatus), kError);
  EXPECT_EQ(rig.buffer.PageAt(0x40), SomePage(50));
  EXPECT_EQ(rig.chip.PageAt(0, 0), SomePage());
}

// The registers are the CPU's to write at any time. What a command is
// about is what they said when it was given.
TEST(WhenTheCpuChangesTheRegistersAfterGivingAFlashControllerACommand,
     TheCommandIsCarriedOutAsItWasGiven) {
  Rig rig;
  rig.chip.array.ProgramPage(2, 5, SomePage());
  rig.Write32(kBlock, 2);
  rig.Write32(kPage, 5);
  rig.Write32(kLocalAddress, 0x40);
  rig.Write32(kCommand, kReadPage);

  rig.Write32(kBlock, 0);
  rig.Write32(kPage, 0);
  rig.Write32(kLocalAddress, 0x80);
  rig.controller.CarryOut();

  EXPECT_EQ(rig.buffer.PageAt(0x40), SomePage());
  EXPECT_EQ(rig.buffer.PageAt(0x80),
            std::vector<std::uint8_t>(kSmall.page_size, 0));
}

}  // namespace socpuppet
