#include "socpuppet/core/virtqueue.h"

#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <vector>

#include <gtest/gtest.h>

#include "tests/cpp/support/memory_at.h"
#include "tests/cpp/support/virtqueue_driver.h"

namespace socpuppet {

namespace {

// Where the driver's memory is in these tests, 64 KiB of it, above 4 GiB so
// that an address in it needs all of its 64 bits.
constexpr std::uint64_t kMemory = 0x1'0000'0000;

constexpr std::uint16_t kReadable = VirtqueueDriver::kReadable;
constexpr std::uint16_t kNext = VirtqueueDriver::kNext;
constexpr std::uint16_t kWrite = VirtqueueDriver::kWrite;

// `length` bytes in which no two neighbours are the same, and which do not
// repeat every 256 bytes, so that bytes read from the wrong buffer (they
// are 0x100 apart) are not taken for the right ones.
std::vector<std::uint8_t> SomeBytes(std::size_t length) {
  std::vector<std::uint8_t> data(length);
  for (std::size_t index = 0; index < data.size(); ++index) {
    data[index] = static_cast<std::uint8_t>(1 + index + (index / 251));
  }
  return data;
}

// A split virtqueue of `kSize` entries in the memory, with the driver's
// side and the device's side of it.
struct Rig {
  static constexpr std::uint16_t kSize = 8;
  static constexpr Virtqueue::Layout kLayout{.desc = kMemory + 0x1000,
                                             .avail = kMemory + 0x2000,
                                             .used = kMemory + 0x3000,
                                             .size = kSize};

  MemoryAt memory{kMemory};
  VirtqueueDriver driver{memory, kLayout, kMemory + 0x4000};
  Virtqueue queue{memory, kLayout};
};

TEST(WhenTheDriverMakesAChainOfOneReadableDescriptorAvailable,
     TheDeviceGetsTheChainWithItsBytes) {
  Rig rig;
  const std::vector<std::uint8_t> bytes = SomeBytes(48);
  rig.driver.Describe(0, static_cast<std::uint32_t>(bytes.size()), kReadable);
  rig.driver.Fill(0, bytes);
  rig.driver.MakeAvailable(0);

  const std::optional<Virtqueue::Chain> chain = rig.queue.Next();

  ASSERT_TRUE(chain.has_value());
  EXPECT_EQ(rig.queue.Read(*chain), bytes);
}

TEST(WhenTheDriverMakesAChainOfThreeDescriptorsAvailable,
     TheDeviceFollowsNextAndSplitsWhatItReadsFromWhatItWrites) {
  Rig rig;
  const std::vector<std::uint8_t> first = SomeBytes(16);
  const std::vector<std::uint8_t> second = SomeBytes(300);
  rig.driver.Describe(0, static_cast<std::uint32_t>(first.size()),
                      kReadable | kNext, 1);
  rig.driver.Describe(1, static_cast<std::uint32_t>(second.size()),
                      kReadable | kNext, 2);
  const std::uint64_t answer = rig.driver.Describe(2, 64, kWrite);
  rig.driver.Fill(0, first);
  rig.driver.Fill(1, second);
  rig.driver.MakeAvailable(0);

  const std::optional<Virtqueue::Chain> chain = rig.queue.Next();

  ASSERT_TRUE(chain.has_value());
  std::vector<std::uint8_t> both = first;
  both.insert(both.end(), second.begin(), second.end());
  EXPECT_EQ(rig.queue.Read(*chain), both);
  ASSERT_EQ(chain->writable.size(), 1U);
  EXPECT_EQ(chain->writable.front().address, answer);
  EXPECT_EQ(chain->writable.front().length, 64U);
}

TEST(WhenTheDriverHasMadeNothingMoreAvailable, TheDeviceGetsNoChain) {
  Rig rig;
  rig.driver.Describe(0, 8, kReadable);
  rig.driver.MakeAvailable(0);
  rig.queue.Next();

  EXPECT_FALSE(rig.queue.Next().has_value());
}

TEST(
    WhenTheDeviceHasUsedAChain,
    TheUsedRingHoldsTheChainsHeadAndHowManyBytesWereWrittenAndItsIndexMovesOn) {
  Rig rig;
  rig.driver.Describe(3, 64, kWrite);
  rig.driver.MakeAvailable(3);
  const std::optional<Virtqueue::Chain> chain = rig.queue.Next();
  ASSERT_TRUE(chain.has_value());

  rig.queue.Used(*chain, 20);

  EXPECT_EQ(rig.driver.UsedIndex(), 1);
  EXPECT_EQ(rig.driver.UsedAt(0).id, 3U);
  EXPECT_EQ(rig.driver.UsedAt(0).length, 20U);
}

TEST(WhenTheDeviceHasUsedMoreChainsThanTheQueueHasEntries,
     TheNextElementGoesAtTheStartOfTheUsedRingAndTheIndexKeepsCounting) {
  Rig rig;
  // Each round writes its own number, so the used ring says which round
  // filled a slot.
  for (std::uint16_t round = 0; round < Rig::kSize + 1; ++round) {
    const std::uint16_t head = round % Rig::kSize;
    rig.driver.Describe(head, 8, kWrite);
    rig.driver.MakeAvailable(head);
    const std::optional<Virtqueue::Chain> chain = rig.queue.Next();
    ASSERT_TRUE(chain.has_value());
    rig.queue.Used(*chain, /*written=*/round);
  }
  const std::uint16_t ninth_round = Rig::kSize;

  EXPECT_EQ(rig.driver.UsedIndex(), Rig::kSize + 1);
  EXPECT_EQ(rig.driver.UsedAt(0).length, ninth_round);
}

TEST(WhenTheDriverMakesAChainThatLoopsBackOnItselfAvailable,
     TheDeviceRefusesItAndSaysTheQueueIsBroken) {
  Rig rig;
  rig.driver.Describe(0, 8, kReadable | kNext, 1);
  rig.driver.Describe(1, 8, kReadable | kNext, 0);
  rig.driver.MakeAvailable(0);

  EXPECT_FALSE(rig.queue.Next().has_value());
  EXPECT_TRUE(rig.queue.Broken());
}

TEST(WhenTheDriverMakesMoreAvailableAfterAChainThatLooped,
     TheDeviceStillGetsNothingFromTheBrokenQueue) {
  Rig rig;
  rig.driver.Describe(0, 8, kReadable | kNext, 0);
  rig.driver.MakeAvailable(0);
  rig.queue.Next();
  rig.driver.Describe(1, 8, kReadable);
  rig.driver.MakeAvailable(1);

  EXPECT_FALSE(rig.queue.Next().has_value());
}

TEST(WhenTheDeviceWritesMoreThanAChainsTwoWritableBuffersHold,
     TheFirstIsFilledThenTheSecondAndItIsToldHowManyBytesWent) {
  Rig rig;
  rig.driver.Describe(0, 16, kWrite | kNext, 1);
  rig.driver.Describe(1, 16, kWrite);
  rig.driver.MakeAvailable(0);
  const std::optional<Virtqueue::Chain> chain = rig.queue.Next();
  ASSERT_TRUE(chain.has_value());
  const std::vector<std::uint8_t> bytes = SomeBytes(40);

  const std::uint32_t went = rig.queue.Write(*chain, bytes);

  EXPECT_EQ(went, 32U);
  EXPECT_EQ(rig.driver.Contents(0, 16),
            std::vector<std::uint8_t>(bytes.begin(), bytes.begin() + 16));
  EXPECT_EQ(rig.driver.Contents(1, 16),
            std::vector<std::uint8_t>(bytes.begin() + 16, bytes.begin() + 32));
}

}  // namespace

}  // namespace socpuppet
