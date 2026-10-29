#include "socpuppet/core/virtio_rng_logic.h"

#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

#include <gtest/gtest.h>

#include "socpuppet/core/virtqueue.h"
#include "tests/cpp/support/memory_at.h"
#include "tests/cpp/support/virtqueue_driver.h"

namespace socpuppet {

namespace {

// Where the driver's memory is in these tests, 64 KiB of it.
constexpr std::uint64_t kMemory = 0x8000'0000;

// The entropy device's one queue, with the driver's side and the device's
// side of it, and the device itself.
struct Rig {
  static constexpr Virtqueue::Layout kQueue{
      .desc = kMemory + 0x1000,
      .avail = kMemory + 0x2000,
      .used = kMemory + 0x3000,
      .size = 8,
  };

  explicit Rig(std::uint64_t seed) : rng(seed) {}

  // Asks the device for `length` bytes: a writable chain, handed over.
  // The buffer starts out full of `before`, so that a byte the device did
  // not write shows.
  std::vector<std::uint8_t> Ask(std::uint32_t length, std::uint8_t before = 0) {
    driver.Describe(0, length, VirtqueueDriver::kWrite);
    driver.Fill(0, std::vector<std::uint8_t>(length, before));
    driver.MakeAvailable(0);
    const Virtqueue::Chain chain = NextChain(queue);
    rng.Handle(0, chain, queue);
    return driver.Contents(0, length);
  }

  MemoryAt memory{kMemory};
  VirtqueueDriver driver{memory, kQueue, kMemory + 0x4000};
  Virtqueue queue{memory, kQueue};
  VirtioRngLogic rng;
};

TEST(WhenTheDriverAsksAnEntropyDeviceForBytes,
     TheWholeBufferIsFilledAndGivenBackForItsWholeLength) {
  // Two devices with the same seed give the same bytes, so a byte that was
  // not written is the one place the two buffers could differ.
  Rig first{1};
  Rig second{1};

  const std::vector<std::uint8_t> bytes = first.Ask(64, 0x00);

  EXPECT_EQ(bytes, second.Ask(64, 0xFF));
  EXPECT_EQ(first.driver.UsedAt(0).length, 64U);
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
