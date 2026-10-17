#include "socpuppet/core/virtio_rng_logic.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <vector>

#include <gtest/gtest.h>

#include "socpuppet/core/memory_port.h"
#include "socpuppet/core/memory_store.h"
#include "socpuppet/core/virtqueue.h"
#include "tests/cpp/support/virtqueue_driver.h"

namespace socpuppet {

namespace {

// Where the driver's memory is in these tests, 64 KiB of it.
constexpr std::uint64_t kMemory = 0x8000'0000;
constexpr std::size_t kMemorySize = 0x1'0000;

// A memory at some address.
class MemoryAt : public MemoryPort {
 public:
  explicit MemoryAt(std::uint64_t base) : base_(base) {}

  bool Read(std::uint64_t address, std::span<std::uint8_t> out) override {
    return address >= base_ && store_.Read(address - base_, out);
  }
  bool Write(std::uint64_t address, std::span<const std::uint8_t> in) override {
    return address >= base_ && store_.Write(address - base_, in);
  }

 private:
  std::uint64_t base_;
  MemoryStore store_{kMemorySize};
};

// The entropy device's one queue, with the driver's side and the device's
// side of it, and the device itself.
struct Rig {
  static constexpr Virtqueue::Layout kQueue{.desc = kMemory + 0x1000,
                                            .avail = kMemory + 0x2000,
                                            .used = kMemory + 0x3000,
                                            .size = 8};

  explicit Rig(std::uint64_t seed) : rng(seed) {}

  // Asks the device for `length` bytes: a writable chain, handed over.
  std::vector<std::uint8_t> Ask(std::uint32_t length) {
    driver.Describe(0, length, VirtqueueDriver::kWrite);
    driver.MakeAvailable(0);
    const std::optional<Virtqueue::Chain> chain = queue.Next();
    EXPECT_TRUE(chain.has_value());
    rng.Handle(0, *chain, queue);
    return driver.Contents(0, length);
  }

  MemoryAt memory{kMemory};
  VirtqueueDriver driver{memory, kQueue, kMemory + 0x4000};
  Virtqueue queue{memory, kQueue};
  VirtioRngLogic rng;
};

TEST(WhenTheDriverAsksAnEntropyDeviceForBytes,
     TheWholeBufferIsFilledAndGivenBackForItsWholeLength) {
  Rig rig{1};

  const std::vector<std::uint8_t> bytes = rig.Ask(64);

  EXPECT_EQ(rig.driver.UsedAt(0).length, 64U);
  EXPECT_NE(std::ranges::count(bytes, 0), 64);
}

TEST(WhenTwoEntropyDevicesAreBuiltWithTheSameSeed, TheyGiveTheSameBytes) {
  Rig first{7};
  Rig second{7};

  EXPECT_EQ(first.Ask(32), second.Ask(32));
}

TEST(WhenTwoEntropyDevicesAreBuiltWithDifferentSeeds, TheirBytesDiffer) {
  Rig first{7};
  Rig second{8};

  EXPECT_NE(first.Ask(32), second.Ask(32));
}

}  // namespace

}  // namespace socpuppet
