#include "socpuppet/core/prp.h"

#include <cstdint>
#include <map>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>

namespace socpuppet {

using ::testing::ElementsAre;

// A page of memory, and one entry of a list of pages.
constexpr std::uint64_t kPage = 4096;
constexpr std::uint64_t kEntry = 8;

// A host with no PRP lists in its memory, for data that needs none.
std::uint64_t NoLists(std::uint64_t) { return 0; }

TEST(WhenACommandsDataFitsInItsFirstPage, ItIsOnePieceAtTheFirstEntry) {
  EXPECT_THAT(PrpExtents(/*prp1=*/0x1000, /*prp2=*/0, /*length=*/512, NoLists),
              ElementsAre(HostExtent{0x1000, 512}));
}

TEST(WhenACommandsDataStartsPartWayIntoAPageAndRunsOverItsEnd,
     TheRestIsAtTheSecondEntry) {
  // 0x100 bytes are left in the first page, and the other 0x100 go to the
  // start of the page the second entry names.
  EXPECT_THAT(
      PrpExtents(/*prp1=*/0x1F00, /*prp2=*/0x8000, /*length=*/0x200, NoLists),
      ElementsAre(HostExtent{0x1F00, 0x100}, HostExtent{0x8000, 0x100}));
}

TEST(WhenACommandsDataTakesMoreThanTwoPages,
     TheSecondEntryPointsToAListOfThePagesAfterTheFirst) {
  // Three pages of data. The list is at 0x9000 and names the second and
  // third pages.
  const std::map<std::uint64_t, std::uint64_t> lists{{0x9000, 0x5000},
                                                     {0x9008, 0x3000}};

  EXPECT_THAT(
      PrpExtents(/*prp1=*/0x1000, /*prp2=*/0x9000, /*length=*/3 * kPage,
                 [&](std::uint64_t address) { return lists.at(address); }),
      ElementsAre(HostExtent{0x1000, 4096}, HostExtent{0x5000, 4096},
                  HostExtent{0x3000, 4096}));
}

TEST(WhenAListOfPagesIsLongerThanAPageOfMemory,
     ItsLastEntryPointsToTheRestOfTheList) {
  // A page holds 512 entries. With more than that still to name, the 512th
  // is not a page of data but the address of the next page of the list.
  // 514 pages of data: the first from the command, 511 from the first page
  // of the list at 0x10'0000, and 2 from its second page at 0x20'0000.
  constexpr std::uint64_t kFirstList = 0x10'0000;
  constexpr std::uint64_t kSecondList = 0x20'0000;
  const auto read_entry = [&](std::uint64_t address) -> std::uint64_t {
    if (address == kFirstList + (511 * kEntry)) return kSecondList;
    // Every other entry names a page whose address says which entry it was.
    return address * 0x1000;
  };

  const std::vector<HostExtent> extents = PrpExtents(
      /*prp1=*/0x1000, /*prp2=*/kFirstList, /*length=*/514 * kPage, read_entry);

  ASSERT_EQ(extents.size(), 514U);
  EXPECT_EQ(extents[511],
            (HostExtent{(kFirstList + (510 * kEntry)) * 0x1000, 4096}));
  EXPECT_EQ(extents[512], (HostExtent{kSecondList * 0x1000, 4096}));
  EXPECT_EQ(extents[513], (HostExtent{(kSecondList + 8) * 0x1000, 4096}));
}

TEST(WhenAListOfPagesExactlyFillsAPageOfMemory, ItsLastEntryIsAPageOfData) {
  // 513 pages of data: the first from the command, and 512 from a list
  // that takes up the whole page at 0x10'0000. Nothing is left over, so
  // the list's last entry names the last page and is not a link.
  constexpr std::uint64_t kList = 0x10'0000;
  const auto read_entry = [](std::uint64_t address) -> std::uint64_t {
    return address * 0x1000;
  };

  const std::vector<HostExtent> extents = PrpExtents(
      /*prp1=*/0x1000, /*prp2=*/kList, /*length=*/513 * kPage, read_entry);

  ASSERT_EQ(extents.size(), 513U);
  EXPECT_EQ(extents[512],
            (HostExtent{(kList + (511 * kEntry)) * 0x1000, 4096}));
}

}  // namespace socpuppet
