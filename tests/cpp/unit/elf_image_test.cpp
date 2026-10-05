#include "socpuppet/core/elf_image.h"

#include <cstdint>
#include <fstream>
#include <ios>
#include <iterator>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>

#include "tests/cpp/support/elf_file.h"

using socpuppet::ElfImage;
using socpuppet::ReadElfImage;
using ::testing::HasSubstr;
using ::testing::Pair;
using ::testing::ThrowsMessage;
using ::testing::UnorderedElementsAre;

std::vector<std::pair<std::uint64_t, std::string>> AddressesAndText(
    const ElfImage& image);

TEST(WhenAnElfImageIsRead, EachLoadableSegmentComesWithItsPhysicalAddress) {
  const ElfFile file{.segments = {{.physical_address = 0x8000'0000,
                                   .virtual_address = 0xC000'0000,
                                   .bytes = "first segment"},
                                  {.physical_address = 0x8000'1000,
                                   .virtual_address = 0xC000'1000,
                                   .bytes = "second"}}};

  const ElfImage image = ReadElfImage(file.Write());

  EXPECT_THAT(AddressesAndText(image),
              UnorderedElementsAre(Pair(0x8000'0000U, "first segment"),
                                   Pair(0x8000'1000U, "second")));
}

TEST(WhenAnElfImageIsRead, ASegmentThatIsNotLoadableIsLeftOut) {
  const ElfFile file{.segments = {{.physical_address = 0x8000'0000,
                                   .virtual_address = 0x8000'0000,
                                   .bytes = "program"},
                                  {.physical_address = 0,
                                   .virtual_address = 0,
                                   .bytes = "a note",
                                   .loadable = false}}};

  const ElfImage image = ReadElfImage(file.Write());

  EXPECT_THAT(AddressesAndText(image),
              UnorderedElementsAre(Pair(0x8000'0000U, "program")));
}

TEST(WhenAnElfImageIsRead, ALoadableSegmentWithNoBytesInTheFileIsLeftOut) {
  const ElfFile file{.segments = {{.physical_address = 0x8000'0000,
                                   .virtual_address = 0x8000'0000,
                                   .bytes = "program"},
                                  {.physical_address = 0x8000'2000,
                                   .virtual_address = 0x8000'2000,
                                   .bytes = ""}}};

  const ElfImage image = ReadElfImage(file.Write());

  EXPECT_THAT(AddressesAndText(image),
              UnorderedElementsAre(Pair(0x8000'0000U, "program")));
}

TEST(WhenAnElfImageIsRead, ItSaysWhichWordSizeItWasBuiltFor) {
  ElfFile file;

  file.xlen = 32;
  EXPECT_EQ(ReadElfImage(file.Write()).xlen, 32U);
  file.xlen = 64;
  EXPECT_EQ(ReadElfImage(file.Write()).xlen, 64U);
}

TEST(WhenAnElfImageIsRead, ItSaysWhereExecutionStarts) {
  ElfFile file;
  file.entry = 0x8000'0040;

  EXPECT_EQ(ReadElfImage(file.Write()).entry, 0x8000'0040U);
}

TEST(WhenAFileIsNotAnElfImage, ReadingItIsRefusedAndTheErrorNamesTheFile) {
  const std::string path = ::testing::TempDir() + "not_an_elf_image.txt";
  std::ofstream{path} << "This is not the file you are looking for.";

  EXPECT_THAT(
      [&] { ReadElfImage(path); },
      ThrowsMessage<std::invalid_argument>(HasSubstr("not_an_elf_image.txt")));
}

TEST(WhenAnElfImageHasLostItsEnd, ReadingItIsRefusedAndTheErrorNamesTheFile) {
  const ElfFile file{.segments = {{.physical_address = 0x8000'0000,
                                   .virtual_address = 0x8000'0000,
                                   .bytes = std::string(4096, 'x')}}};
  const std::string path = file.Write();
  // Cut the file off part of the way through its only segment.
  std::string contents;
  {
    std::ifstream whole{path, std::ios::binary};
    contents.assign(std::istreambuf_iterator<char>{whole}, {});
  }
  std::ofstream{path, std::ios::binary | std::ios::trunc}
      << contents.substr(0, contents.size() - 2048);

  EXPECT_THAT([&] { ReadElfImage(path); },
              ThrowsMessage<std::invalid_argument>(HasSubstr(path)));
}

// Each segment of `image` as its address and its bytes, read as text.
std::vector<std::pair<std::uint64_t, std::string>> AddressesAndText(
    const ElfImage& image) {
  std::vector<std::pair<std::uint64_t, std::string>> result;
  result.reserve(image.segments.size());
  for (const ElfImage::Segment& each : image.segments) {
    result.emplace_back(
        each.address,
        std::string{reinterpret_cast<const char*>(each.bytes.data()),
                    each.bytes.size()});
  }
  return result;
}
