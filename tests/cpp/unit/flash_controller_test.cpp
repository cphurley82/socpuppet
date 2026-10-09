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

// The bits of the status register.
constexpr std::uint32_t kDone = 1U << 0;
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

}  // namespace socpuppet
