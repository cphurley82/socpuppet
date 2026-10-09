#include "socpuppet/core/flash_controller.h"

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

// The controller's registers, each 32 bits wide, as its page in
// docs/models/ gives them.
constexpr std::uint64_t kCommand = 0x00;
constexpr std::uint64_t kStatus = 0x04;
constexpr std::uint64_t kBlock = 0x0C;
constexpr std::uint64_t kPage = 0x10;
constexpr std::uint64_t kLocal = 0x14;

// What can be written to the command register.
constexpr std::uint32_t kReadPage = 1;
constexpr std::uint32_t kProgramPage = 2;
constexpr std::uint32_t kEraseBlock = 3;

// The bits of the status register.
constexpr std::uint32_t kDone = 1U << 0;
constexpr std::uint32_t kError = 1U << 1;
constexpr std::uint32_t kBusy = 1U << 2;

// A small chip: 4 blocks of 8 pages, each page 16 bytes.
constexpr NandGeometry kSmall{
    .page_size = 16, .pages_per_block = 8, .blocks = 4};

// A chip on the controller's NAND port.
class Chip : public NandPort {
 public:
  NandArray array{kSmall};

  std::optional<NandGeometry> Geometry() override { return array.geometry(); }
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

// A controller with a chip and a buffer, as its CPU sees it.
struct Rig {
  Chip chip;
  Buffer buffer;
  FlashController controller{chip, buffer};

  bool Write32(std::uint64_t offset, std::uint32_t value) {
    return controller.WriteRegister(offset, LittleEndianBytes(value));
  }
  std::uint32_t Read32(std::uint64_t offset) {
    std::array<std::uint8_t, 4> bytes{};
    EXPECT_TRUE(controller.ReadRegister(offset, bytes));
    return LoadLittleEndian<std::uint32_t>(bytes);
  }
};

}  // namespace

TEST(WhenAFlashControllerIsToldToReadAPage, ThePageArrivesInLocalMemory) {
  Rig rig;
  rig.chip.array.ProgramPage(2, 5, SomePage());
  rig.Write32(kBlock, 2);
  rig.Write32(kPage, 5);
  rig.Write32(kLocal, 0x40);

  rig.Write32(kCommand, kReadPage);
  rig.controller.CarryOut();

  EXPECT_EQ(rig.buffer.PageAt(0x40), SomePage());
  EXPECT_EQ(rig.Read32(kStatus) & kDone, kDone);
}

TEST(WhenAFlashControllerHasNotYetCarriedOutACommand,
     ItsStatusSaysBusyAndNotDone) {
  Rig rig;

  rig.Write32(kCommand, kReadPage);

  EXPECT_EQ(rig.Read32(kStatus) & (kBusy | kDone), kBusy);
}

TEST(WhenAFlashControllerHasCarriedOutACommand, ItsStatusNoLongerSaysBusy) {
  Rig rig;
  rig.Write32(kCommand, kReadPage);

  rig.controller.CarryOut();

  EXPECT_EQ(rig.Read32(kStatus) & kBusy, 0U);
}

TEST(WhenAFlashControllerIsToldToProgramAPage,
     TheChipsPageHoldsWhatLocalMemoryHeld) {
  Rig rig;
  rig.buffer.store.Write(0x40, SomePage());
  rig.Write32(kBlock, 2);
  rig.Write32(kPage, 5);
  rig.Write32(kLocal, 0x40);

  rig.Write32(kCommand, kProgramPage);
  rig.controller.CarryOut();

  EXPECT_EQ(rig.chip.PageAt(2, 5), SomePage());
  EXPECT_EQ(rig.Read32(kStatus) & kDone, kDone);
}

TEST(WhenAFlashControllerIsToldToEraseABlock, TheBlocksPagesReadAsAllOnes) {
  Rig rig;
  rig.chip.array.ProgramPage(2, 5, SomePage());
  rig.Write32(kBlock, 2);

  rig.Write32(kCommand, kEraseBlock);
  rig.controller.CarryOut();

  EXPECT_EQ(rig.chip.PageAt(2, 5),
            std::vector<std::uint8_t>(kSmall.page_size, 0xFF));
  EXPECT_EQ(rig.Read32(kStatus) & kDone, kDone);
}

// Block 4 is one past the end of the chip.
TEST(WhenTheChipRefusesWhatAFlashControllerAsksOfIt,
     TheStatusSaysErrorAndNotDone) {
  for (const std::uint32_t command : {kReadPage, kProgramPage, kEraseBlock}) {
    Rig rig;
    rig.Write32(kBlock, 4);

    rig.Write32(kCommand, command);
    rig.controller.CarryOut();

    EXPECT_EQ(rig.Read32(kStatus), kError) << "command " << command;
  }
}

// The buffer is 256 bytes long, so nothing answers at 0x1000.
TEST(WhenLocalMemoryDoesNotTakeThePageAFlashControllerRead,
     TheStatusSaysErrorAndNotDone) {
  Rig rig;
  rig.Write32(kLocal, 0x1000);

  rig.Write32(kCommand, kReadPage);
  rig.controller.CarryOut();

  EXPECT_EQ(rig.Read32(kStatus), kError);
}

TEST(WhenLocalMemoryDoesNotGiveThePageAFlashControllerIsToProgram,
     TheStatusSaysErrorAndTheChipIsLeftAlone) {
  Rig rig;
  rig.Write32(kLocal, 0x1000);

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
  rig.Write32(kLocal, 0x40);
  rig.Write32(kCommand, kReadPage);

  EXPECT_FALSE(rig.Write32(kCommand, kEraseBlock));
  rig.controller.CarryOut();

  EXPECT_EQ(rig.buffer.PageAt(0x40), SomePage());
  EXPECT_EQ(rig.chip.PageAt(2, 5), SomePage());
}

TEST(WhenAFlashControllerIsGivenACommandItDoesNotHave, TheWriteIsRefused) {
  Rig rig;

  EXPECT_FALSE(rig.Write32(kCommand, 0));
  EXPECT_FALSE(rig.Write32(kCommand, 4));
  EXPECT_EQ(rig.Read32(kStatus), 0U);
}

TEST(WhenOneIsWrittenToAStatusBitOfAFlashController, TheBitIsCleared) {
  Rig done;
  done.Write32(kCommand, kReadPage);
  done.controller.CarryOut();
  Rig error;
  error.Write32(kBlock, 4);
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

}  // namespace socpuppet
