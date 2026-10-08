#include "socpuppet/core/little_endian.h"

#include <array>
#include <cstdint>

#include <gmock/gmock.h>
#include <gtest/gtest.h>

namespace socpuppet {

using ::testing::ElementsAre;

TEST(WhenANumberIsStoredLittleEndian, ItsLeastSignificantByteComesFirst) {
  std::array<std::uint8_t, 4> bytes{};

  StoreLittleEndian<std::uint32_t>(0x1234'5678, bytes);

  EXPECT_THAT(bytes, ElementsAre(0x78, 0x56, 0x34, 0x12));
}

TEST(WhenANumberIsStoredLittleEndian, TheBytesAfterItAreLeftAlone) {
  std::array<std::uint8_t, 4> bytes{0xAA, 0xAA, 0xAA, 0xAA};

  StoreLittleEndian<std::uint16_t>(0x1234, bytes);

  EXPECT_THAT(bytes, ElementsAre(0x34, 0x12, 0xAA, 0xAA));
}

TEST(WhenANumberIsLoadedLittleEndian, TheFirstByteIsItsLeastSignificant) {
  const std::array<std::uint8_t, 4> bytes{0x78, 0x56, 0x34, 0x12};

  EXPECT_EQ(LoadLittleEndian<std::uint32_t>(bytes), 0x1234'5678U);
}

TEST(WhenANumberIsLoadedLittleEndian, OnlyAsManyBytesAsItHasAreRead) {
  const std::array<std::uint8_t, 4> bytes{0x78, 0x56, 0x34, 0x12};

  EXPECT_EQ(LoadLittleEndian<std::uint16_t>(bytes), 0x5678U);
}

TEST(WhenA64BitNumberGoesThereAndBack, ItComesBackWhole) {
  std::array<std::uint8_t, 8> bytes{};

  StoreLittleEndian<std::uint64_t>(0x0123'4567'89AB'CDEF, bytes);

  EXPECT_EQ(LoadLittleEndian<std::uint64_t>(bytes), 0x0123'4567'89AB'CDEFU);
}

TEST(WhenANumbersBytesAreAskedFor, TheyAreItsLittleEndianBytes) {
  EXPECT_THAT(LittleEndianBytes<std::uint32_t>(0x1234'5678),
              ElementsAre(0x78, 0x56, 0x34, 0x12));
}

}  // namespace socpuppet
