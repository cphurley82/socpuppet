#include <array>
#include <cstdint>
#include <limits>

#include <gtest/gtest.h>

#include "socpuppet/core/memory_store.h"

using socpuppet::MemoryStore;

TEST(WhenBytesWereNeverWritten, TheyReadBackAsZero) {
  MemoryStore store{16};
  std::array<std::uint8_t, 4> bytes{0xAA, 0xAA, 0xAA, 0xAA};

  store.read(4, bytes);

  EXPECT_EQ(bytes, (std::array<std::uint8_t, 4>{0, 0, 0, 0}));
}

TEST(WhenBytesAreReadAfterBeingWritten, TheReadReturnsTheWrittenBytes) {
  MemoryStore store{16};
  const std::array<std::uint8_t, 3> written{0x11, 0x22, 0x33};
  std::array<std::uint8_t, 3> read{};

  store.write(5, written);
  store.read(5, read);

  EXPECT_EQ(read, written);
}

TEST(WhenAnAccessRunsPastTheEnd, AWriteIsRejectedAndChangesNothing) {
  MemoryStore store{4};
  const std::array<std::uint8_t, 4> too_long{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> contents{};

  const bool accepted = store.write(2, too_long);
  store.read(0, contents);

  EXPECT_FALSE(accepted);
  EXPECT_EQ(contents, (std::array<std::uint8_t, 4>{0, 0, 0, 0}));
}

TEST(WhenAnAccessRunsPastTheEnd, AReadIsRejected) {
  MemoryStore store{4};
  std::array<std::uint8_t, 4> too_long{};

  EXPECT_FALSE(store.read(2, too_long));
}

TEST(WhenAnAccessStartsPastTheEnd, ItIsRejected) {
  MemoryStore store{4};
  std::array<std::uint8_t, 1> one_byte{};

  EXPECT_FALSE(store.read(5, one_byte));
}

TEST(WhenAnOffsetIsSoLargeThatAddingTheLengthWrapsAround, TheAccessIsRejected) {
  MemoryStore store{4};
  std::array<std::uint8_t, 2> two_bytes{};

  EXPECT_FALSE(store.read(std::numeric_limits<std::size_t>::max(), two_bytes));
}
