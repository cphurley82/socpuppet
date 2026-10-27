#include <cstdint>
#include <map>
#include <optional>

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <rvi/iommu_walker.h>

namespace vpvper::rvi {

namespace {

using ::testing::Optional;

// Memory as the walker sees it: 8-byte words at physical addresses. A word
// nobody put there does not answer.
class Memory {
 public:
  Memory() = default;
  // The walker's loader points here.
  Memory(const Memory&) = delete;
  Memory& operator=(const Memory&) = delete;

  iommu_walker::load_fn Loader() {
    return [this](std::uint64_t pa, std::uint64_t& value) {
      const auto word = words_.find(pa);
      if (word == words_.end()) return false;
      value = word->second;
      return true;
    };
  }

  void Put(std::uint64_t pa, std::uint64_t word) { words_[pa] = word; }

 private:
  std::map<std::uint64_t, std::uint64_t> words_;
};

// The V bit of a device context's tc and of a directory entry: what it
// holds is valid.
constexpr std::uint64_t kV = 1;

// A device context in the base format, 32 bytes: translation control, the
// second stage's table, translation attributes, the first stage's table.
struct DeviceContext {
  std::uint64_t tc = 0;
  std::uint64_t iohgatp = 0;
  std::uint64_t ta = 0;
  std::uint64_t fsc = 0;
};
constexpr std::uint64_t kDeviceContextSize = 32;

// Puts `context` at entry `index` of the leaf table of a device directory
// at `table`.
void PutDeviceContext(Memory& memory, std::uint64_t table, std::uint64_t index,
                      const DeviceContext& context) {
  const std::uint64_t at = table + (index * kDeviceContextSize);
  memory.Put(at, context.tc);
  memory.Put(at + 8, context.iohgatp);
  memory.Put(at + 16, context.ta);
  memory.Put(at + 24, context.fsc);
}

// What the MODE field of fsc, bits 63:60, says a device's first stage of
// translation is.
enum class FirstStage : std::uint64_t {
  kBare = 0,
  kSv39 = 8,
  kSv48 = 9,
};

// The fsc of a device context whose first stage is `mode`, with its root
// page table at `root`.
std::uint64_t Fsc(FirstStage mode, std::uint64_t root = 0) {
  return (static_cast<std::uint64_t>(mode) << 60) | (root >> 12);
}

// A non-leaf entry of a device directory, pointing at the table below.
std::uint64_t Ddte(std::uint64_t next) { return ((next >> 12) << 10) | kV; }

// Puts `entry` at entry `index` of a non-leaf table at `table`.
void PutDdte(Memory& memory, std::uint64_t table, std::uint64_t index,
             std::uint64_t entry) {
  memory.Put(table + (index * 8), entry);
}

// Where the tests put the tables of a device directory.
constexpr std::uint64_t kRoot = 0x8010'0000;
constexpr std::uint64_t kMiddle = 0x8020'0000;
constexpr std::uint64_t kLeaf = 0x8030'0000;

// A device ID's index into each level of a directory: bits 6:0 index the
// leaf table, 15:7 the one above it, 23:16 the root of three levels. Each is
// different, and none is 0, so a walker that indexes a level wrongly finds
// nothing there.
constexpr std::uint32_t kDdi0 = 0x05;
constexpr std::uint32_t kDdi1 = 0x0A3;
constexpr std::uint32_t kDdi2 = 0x7C;

// A device ID made of its indexes into a directory's levels.
constexpr std::uint32_t DeviceId(std::uint32_t ddi1, std::uint32_t ddi0) {
  return (ddi1 << 7) | ddi0;
}
constexpr std::uint32_t DeviceId(std::uint32_t ddi2, std::uint32_t ddi1,
                                 std::uint32_t ddi0) {
  return (ddi2 << 16) | DeviceId(ddi1, ddi0);
}

// A read by some device of some address, for the tests where neither
// matters.
constexpr iommu_request kSomeRead{
    .device_id = 0x21, .iova = 0x8000'1234, .is_write = false};

// The same read, by `device_id`.
constexpr iommu_request SomeReadBy(std::uint32_t device_id) {
  iommu_request read = kSomeRead;
  read.device_id = device_id;
  return read;
}

// Sv39's page-table entries: the page they name in bits 53:10, and what
// they allow in the bits below.
constexpr std::uint64_t kR = 1U << 1;  // read
constexpr std::uint64_t kW = 1U << 2;  // write
constexpr std::uint64_t kX = 1U << 3;  // execute
constexpr std::uint64_t kU = 1U << 4;  // by user mode, which a device is
constexpr std::uint64_t kA = 1U << 6;  // accessed
constexpr std::uint64_t kD = 1U << 7;  // dirty
std::uint64_t Pte(std::uint64_t page, std::uint64_t flags) {
  return ((page >> 12) << 10) | flags;
}
// A page a device may read and write, already accessed and dirty, as
// Linux's IOMMU driver makes one.
constexpr std::uint64_t kReadWrite = kV | kR | kW | kU | kA | kD;

// Puts `entry` at the index `vpn` of a page table at `table`.
void PutPte(Memory& memory, std::uint64_t table, std::uint64_t vpn,
            std::uint64_t entry) {
  memory.Put(table + (vpn * 8), entry);
}

// Where the tests put a device's page tables, from the root down.
constexpr std::uint64_t kLevel2 = 0x8040'0000;
constexpr std::uint64_t kLevel1 = 0x8050'0000;
constexpr std::uint64_t kLevel0 = 0x8060'0000;

// An address's index into each level of an Sv39 table, and its offset into
// the page. Each index is different, and none is 0, so a walker that
// indexes a level wrongly finds nothing there.
constexpr std::uint64_t kVpn2 = 0x002;
constexpr std::uint64_t kVpn1 = 0x0C5;
constexpr std::uint64_t kVpn0 = 0x1E3;
constexpr std::uint64_t kOffset = 0x234;
constexpr std::uint64_t kIova =
    (kVpn2 << 30) | (kVpn1 << 21) | (kVpn0 << 12) | kOffset;

// A one-level directory at kRoot, and a device with a context in it whose
// first stage is Sv39, with its root table at kLevel2; and a read by it of
// kIova. PutTranslatedDevice puts the context where kOneLevel finds it.
constexpr iommu_device_directory kOneLevel{.mode = iommu_ddt_mode::one_level,
                                           .root = kRoot};
constexpr std::uint32_t kTranslatedDevice = kDdi0;
constexpr iommu_request kTranslatedRead{
    .device_id = kTranslatedDevice, .iova = kIova, .is_write = false};
// And a write.
constexpr iommu_request kTranslatedWrite{
    .device_id = kTranslatedDevice, .iova = kIova, .is_write = true};
void PutTranslatedDevice(Memory& memory) {
  PutDeviceContext(memory, kRoot, kTranslatedDevice,
                   {.tc = kV, .fsc = Fsc(FirstStage::kSv39, kLevel2)});
}

// Puts the tables down to kLevel0 for kIova, and `leaf` as its entry there.
void PutPage(Memory& memory, std::uint64_t leaf) {
  PutPte(memory, kLevel2, kVpn2, Pte(kLevel1, kV));
  PutPte(memory, kLevel1, kVpn1, Pte(kLevel0, kV));
  PutPte(memory, kLevel0, kVpn0, leaf);
}

// Where the tests map kIova to, in the tests where it does not matter.
constexpr std::uint64_t kSomePage = 0x9ABC'D000;

}  // namespace

TEST(WhenTheDeviceDirectoryIsOff, ARequestIsRefusedAsDmaDisabled) {
  Memory memory;
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate({.mode = iommu_ddt_mode::off, .root = 0}, kSomeRead);

  EXPECT_THAT(translation.fault, Optional(iommu_fault_cause::dma_disabled));
}

TEST(WhenADevicesContextInAOneLevelDirectoryIsNotValid,
     ItsRequestIsRefusedAsDdtInvalid) {
  Memory memory;
  PutDeviceContext(memory, kRoot, kSomeRead.device_id, {.tc = 0});
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation = walker.translate(
      {.mode = iommu_ddt_mode::one_level, .root = kRoot}, kSomeRead);

  EXPECT_THAT(translation.fault, Optional(iommu_fault_cause::ddt_invalid));
}

TEST(WhenTheDeviceDirectoryIsBare, ARequestGoesThroughUntranslated) {
  Memory memory;
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate({.mode = iommu_ddt_mode::bare, .root = 0}, kSomeRead);

  EXPECT_EQ(translation.fault, std::nullopt);
  EXPECT_EQ(translation.pa, kSomeRead.iova);
}

TEST(WhenADeviceHasAValidContextInATwoLevelDirectory,
     ItsRequestGoesThroughUntranslated) {
  Memory memory;
  PutDdte(memory, kRoot, kDdi1, Ddte(kLeaf));
  PutDeviceContext(memory, kLeaf, kDdi0, {.tc = kV});
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate({.mode = iommu_ddt_mode::two_level, .root = kRoot},
                       SomeReadBy(DeviceId(kDdi1, kDdi0)));

  EXPECT_EQ(translation.fault, std::nullopt);
  EXPECT_EQ(translation.pa, kSomeRead.iova);
}

TEST(WhenADeviceHasAValidContextInAThreeLevelDirectory,
     ItsRequestGoesThroughUntranslated) {
  Memory memory;
  PutDdte(memory, kRoot, kDdi2, Ddte(kMiddle));
  PutDdte(memory, kMiddle, kDdi1, Ddte(kLeaf));
  PutDeviceContext(memory, kLeaf, kDdi0, {.tc = kV});
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate({.mode = iommu_ddt_mode::three_level, .root = kRoot},
                       SomeReadBy(DeviceId(kDdi2, kDdi1, kDdi0)));

  EXPECT_EQ(translation.fault, std::nullopt);
  EXPECT_EQ(translation.pa, kSomeRead.iova);
}

TEST(WhenADevicesIdIsWiderThanAOneLevelDirectoryIndexes,
     ItsRequestIsRefusedAsTtypBlocked) {
  // A one-level directory is the leaf table alone, indexed by bits 6:0.
  Memory memory;
  PutDeviceContext(memory, kRoot, kDdi0, {.tc = kV});
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate({.mode = iommu_ddt_mode::one_level, .root = kRoot},
                       SomeReadBy(DeviceId(kDdi1, kDdi0)));

  EXPECT_THAT(translation.fault, Optional(iommu_fault_cause::ttyp_blocked));
}

TEST(WhenTheDirectoryEntryAboveADevicesContextIsNotValid,
     ItsRequestIsRefusedAsDdtInvalid) {
  Memory memory;
  // The entry points at the leaf, but says it is not valid.
  PutDdte(memory, kRoot, kDdi1, Ddte(kLeaf) & ~kV);
  PutDeviceContext(memory, kLeaf, kDdi0, {.tc = kV});
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate({.mode = iommu_ddt_mode::two_level, .root = kRoot},
                       SomeReadBy(DeviceId(kDdi1, kDdi0)));

  EXPECT_THAT(translation.fault, Optional(iommu_fault_cause::ddt_invalid));
}

TEST(WhenNothingAnswersWhereADevicesContextShouldBe,
     ItsRequestIsRefusedAsADdtLoadFault) {
  Memory nothing_there;
  const iommu_walker walker{nothing_there.Loader()};

  const iommu_translation translation = walker.translate(
      {.mode = iommu_ddt_mode::one_level, .root = kRoot}, kSomeRead);

  EXPECT_THAT(translation.fault, Optional(iommu_fault_cause::ddt_load_fault));
}

TEST(WhenNothingAnswersWhereADirectoryEntryShouldBe,
     ItsRequestIsRefusedAsADdtLoadFault) {
  Memory nothing_there;
  const iommu_walker walker{nothing_there.Loader()};

  const iommu_translation translation = walker.translate(
      {.mode = iommu_ddt_mode::three_level, .root = kRoot}, kSomeRead);

  EXPECT_THAT(translation.fault, Optional(iommu_fault_cause::ddt_load_fault));
}

TEST(WhenADirectoryEntryHasAReservedBitSet,
     ItsRequestIsRefusedAsDdtMisconfigured) {
  // Bits 9:1 of a non-leaf entry are reserved.
  constexpr std::uint64_t kReserved = 1U << 1;
  Memory memory;
  PutDdte(memory, kRoot, kDdi1, Ddte(kLeaf) | kReserved);
  PutDeviceContext(memory, kLeaf, kDdi0, {.tc = kV});
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate({.mode = iommu_ddt_mode::two_level, .root = kRoot},
                       SomeReadBy(DeviceId(kDdi1, kDdi0)));

  EXPECT_THAT(translation.fault,
              Optional(iommu_fault_cause::ddt_misconfigured));
}

TEST(WhenADevicesContextAsksForAts, ItsRequestIsRefusedAsDdtMisconfigured) {
  // tc.EN_ATS: the device may ask for translations ahead of time, which
  // this IOMMU does not offer.
  constexpr std::uint64_t kEnableAts = 1U << 1;
  Memory memory;
  PutDeviceContext(memory, kRoot, kSomeRead.device_id, {.tc = kV | kEnableAts});
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation = walker.translate(
      {.mode = iommu_ddt_mode::one_level, .root = kRoot}, kSomeRead);

  EXPECT_THAT(translation.fault,
              Optional(iommu_fault_cause::ddt_misconfigured));
}

TEST(WhenADevicesContextAsksForASecondStage,
     ItsRequestIsRefusedAsDdtMisconfigured) {
  // iohgatp.MODE = Sv39x4, a guest's physical addresses translated again,
  // in bits 63:60. This IOMMU has one stage.
  constexpr std::uint64_t kSv39x4 = std::uint64_t{8} << 60;
  Memory memory;
  PutDeviceContext(memory, kRoot, kSomeRead.device_id,
                   {.tc = kV, .iohgatp = kSv39x4});
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation = walker.translate(
      {.mode = iommu_ddt_mode::one_level, .root = kRoot}, kSomeRead);

  EXPECT_THAT(translation.fault,
              Optional(iommu_fault_cause::ddt_misconfigured));
}

TEST(WhenADevicesContextAsksForAnSv48FirstStage,
     ItsRequestIsRefusedAsDdtMisconfigured) {
  Memory memory;
  PutDeviceContext(memory, kRoot, kSomeRead.device_id,
                   {.tc = kV, .fsc = Fsc(FirstStage::kSv48)});
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation = walker.translate(
      {.mode = iommu_ddt_mode::one_level, .root = kRoot}, kSomeRead);

  EXPECT_THAT(translation.fault,
              Optional(iommu_fault_cause::ddt_misconfigured));
}

TEST(WhenAnSv39TableMapsAPageForADevice,
     ItsRequestGoesToThatPageAtTheSameOffset) {
  constexpr std::uint64_t kPage = 0x9ABC'D000;
  Memory memory;
  PutTranslatedDevice(memory);
  PutPage(memory, Pte(kPage, kReadWrite));
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate(kOneLevel, kTranslatedRead);

  EXPECT_EQ(translation.fault, std::nullopt);
  EXPECT_EQ(translation.pa, kPage + kOffset);
}

TEST(WhenAnSv39TableMapsA2MibPageForADevice,
     ItsRequestGoesToThatPageAtTheSameOffset) {
  // A leaf one level up maps 2 MiB, and the address's last index is part of
  // its offset into it.
  constexpr std::uint64_t kPage = 0x9AC0'0000;
  Memory memory;
  PutTranslatedDevice(memory);
  PutPte(memory, kLevel2, kVpn2, Pte(kLevel1, kV));
  PutPte(memory, kLevel1, kVpn1, Pte(kPage, kReadWrite));
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate(kOneLevel, kTranslatedRead);

  EXPECT_EQ(translation.fault, std::nullopt);
  EXPECT_EQ(translation.pa, kPage + (kVpn0 << 12) + kOffset);
}

TEST(WhenAnSv39TableMapsA1GibPageForADevice,
     ItsRequestGoesToThatPageAtTheSameOffset) {
  // A leaf at the root maps 1 GiB, and the address's last two indexes are
  // part of its offset into it.
  constexpr std::uint64_t kPage = 0xC000'0000;
  Memory memory;
  PutTranslatedDevice(memory);
  PutPte(memory, kLevel2, kVpn2, Pte(kPage, kReadWrite));
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate(kOneLevel, kTranslatedRead);

  EXPECT_EQ(translation.fault, std::nullopt);
  EXPECT_EQ(translation.pa, kPage + (kVpn1 << 21) + (kVpn0 << 12) + kOffset);
}

TEST(WhenTheEntryForAPageIsNotValid, AReadOfItIsRefusedAsAReadPageFault) {
  Memory memory;
  PutTranslatedDevice(memory);
  PutPage(memory, Pte(kSomePage, kReadWrite & ~kV));
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate(kOneLevel, kTranslatedRead);

  EXPECT_THAT(translation.fault, Optional(iommu_fault_cause::read_page_fault));
}

TEST(WhenAPageMayOnlyBeRead, AWriteToItIsRefusedAsAWritePageFault) {
  Memory memory;
  PutTranslatedDevice(memory);
  PutPage(memory, Pte(kSomePage, kReadWrite & ~kW));
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate(kOneLevel, kTranslatedWrite);

  EXPECT_THAT(translation.fault, Optional(iommu_fault_cause::write_page_fault));
}

TEST(WhenTheEntryForAPageIsNotValid, AWriteToItIsRefusedAsAWritePageFault) {
  Memory memory;
  PutTranslatedDevice(memory);
  PutPage(memory, Pte(kSomePage, kReadWrite & ~kV));
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate(kOneLevel, kTranslatedWrite);

  EXPECT_THAT(translation.fault, Optional(iommu_fault_cause::write_page_fault));
}

TEST(WhenAPageMayOnlyBeExecuted, AReadOfItIsRefusedAsAReadPageFault) {
  Memory memory;
  PutTranslatedDevice(memory);
  PutPage(memory, Pte(kSomePage, kV | kX | kU | kA));
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate(kOneLevel, kTranslatedRead);

  EXPECT_THAT(translation.fault, Optional(iommu_fault_cause::read_page_fault));
}

TEST(WhenAPageIsForSupervisorModeOnly,
     ADevicesReadOfItIsRefusedAsAReadPageFault) {
  // A request that carries no process ID is a user-mode access.
  Memory memory;
  PutTranslatedDevice(memory);
  PutPage(memory, Pte(kSomePage, kReadWrite & ~kU));
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate(kOneLevel, kTranslatedRead);

  EXPECT_THAT(translation.fault, Optional(iommu_fault_cause::read_page_fault));
}

TEST(WhenAPageHasNotBeenAccessed, AReadOfItIsRefusedAsAReadPageFault) {
  // This IOMMU does not set A itself; the driver must have.
  Memory memory;
  PutTranslatedDevice(memory);
  PutPage(memory, Pte(kSomePage, kReadWrite & ~kA));
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate(kOneLevel, kTranslatedRead);

  EXPECT_THAT(translation.fault, Optional(iommu_fault_cause::read_page_fault));
}

TEST(WhenAPageIsNotDirty, AWriteToItIsRefusedAsAWritePageFault) {
  // This IOMMU does not set D itself either.
  Memory memory;
  PutTranslatedDevice(memory);
  PutPage(memory, Pte(kSomePage, kReadWrite & ~kD));
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate(kOneLevel, kTranslatedWrite);

  EXPECT_THAT(translation.fault, Optional(iommu_fault_cause::write_page_fault));
}

TEST(WhenAPageMayBeWrittenButNotRead, AWriteToItIsRefusedAsAWritePageFault) {
  // W without R is an encoding Sv39 reserves.
  Memory memory;
  PutTranslatedDevice(memory);
  PutPage(memory, Pte(kSomePage, kReadWrite & ~kR));
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate(kOneLevel, kTranslatedWrite);

  EXPECT_THAT(translation.fault, Optional(iommu_fault_cause::write_page_fault));
}

TEST(WhenA2MibPageIsNotAlignedTo2Mib, AReadOfItIsRefusedAsAReadPageFault) {
  // 4 KiB past a 2 MiB boundary.
  constexpr std::uint64_t kMisaligned = 0x9AC0'1000;
  Memory memory;
  PutTranslatedDevice(memory);
  PutPte(memory, kLevel2, kVpn2, Pte(kLevel1, kV));
  PutPte(memory, kLevel1, kVpn1, Pte(kMisaligned, kReadWrite));
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate(kOneLevel, kTranslatedRead);

  EXPECT_THAT(translation.fault, Optional(iommu_fault_cause::read_page_fault));
}

TEST(WhenAnAddressIsNotOneSv39CanMap, AReadOfItIsRefusedAsAReadPageFault) {
  // Sv39 maps 39 bits: bits 63:39 must all be copies of bit 38.
  constexpr std::uint64_t kBeyondSv39 = kIova | (std::uint64_t{1} << 39);
  Memory memory;
  PutTranslatedDevice(memory);
  PutPage(memory, Pte(kSomePage, kReadWrite));
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation = walker.translate(
      kOneLevel,
      {.device_id = kTranslatedDevice, .iova = kBeyondSv39, .is_write = false});

  EXPECT_THAT(translation.fault, Optional(iommu_fault_cause::read_page_fault));
}

TEST(WhenNothingAnswersWhereAPageTableEntryShouldBe,
     AReadIsRefusedAsAReadAccessFault) {
  Memory memory;
  PutTranslatedDevice(memory);
  // The root's entry points at a table that is not there.
  PutPte(memory, kLevel2, kVpn2, Pte(kLevel1, kV));
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate(kOneLevel, kTranslatedRead);

  EXPECT_THAT(translation.fault,
              Optional(iommu_fault_cause::read_access_fault));
}

TEST(WhenNothingAnswersWhereAPageTableEntryShouldBe,
     AWriteIsRefusedAsAWriteAccessFault) {
  Memory memory;
  PutTranslatedDevice(memory);
  PutPte(memory, kLevel2, kVpn2, Pte(kLevel1, kV));
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate(kOneLevel, kTranslatedWrite);

  EXPECT_THAT(translation.fault,
              Optional(iommu_fault_cause::write_access_fault));
}

TEST(WhenTheLastLevelOfATablePointsAtAnotherTable,
     AReadIsRefusedAsAReadPageFault) {
  // There is no level below the last: its entries must be pages.
  constexpr std::uint64_t kNoSuchLevel = 0x8070'0000;
  Memory memory;
  PutTranslatedDevice(memory);
  PutPage(memory, Pte(kNoSuchLevel, kV));
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate(kOneLevel, kTranslatedRead);

  EXPECT_THAT(translation.fault, Optional(iommu_fault_cause::read_page_fault));
}

TEST(WhenAPageTableEntryHasAReservedBitSet, AReadIsRefusedAsAReadPageFault) {
  // Bits 63:54 are for extensions (memory types, contiguous pages) that
  // this IOMMU does not have; bit 62 would be Svpbmt's.
  constexpr std::uint64_t kReserved = std::uint64_t{1} << 62;
  Memory memory;
  PutTranslatedDevice(memory);
  PutPage(memory, Pte(kSomePage, kReadWrite) | kReserved);
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation =
      walker.translate(kOneLevel, kTranslatedRead);

  EXPECT_THAT(translation.fault, Optional(iommu_fault_cause::read_page_fault));
}

TEST(WhenAnSv39TableMapsAPageInTheUpperHalf,
     ItsRequestGoesToThatPageAtTheSameOffset) {
  // Bit 38 set, and so bits 63:39 as well: index 0x100 of the root, the
  // first of its entries for the upper half.
  constexpr std::uint64_t kUpperHalfOfTheRoot = 0x100;
  constexpr std::uint64_t kUpperIova =
      (~std::uint64_t{0} << 38) | (kVpn1 << 21) | (kVpn0 << 12) | kOffset;
  Memory memory;
  PutTranslatedDevice(memory);
  PutPte(memory, kLevel2, kUpperHalfOfTheRoot, Pte(kLevel1, kV));
  PutPte(memory, kLevel1, kVpn1, Pte(kLevel0, kV));
  PutPte(memory, kLevel0, kVpn0, Pte(kSomePage, kReadWrite));
  const iommu_walker walker{memory.Loader()};

  const iommu_translation translation = walker.translate(
      kOneLevel,
      {.device_id = kTranslatedDevice, .iova = kUpperIova, .is_write = false});

  EXPECT_EQ(translation.fault, std::nullopt);
  EXPECT_EQ(translation.pa, kSomePage + kOffset);
}

}  // namespace vpvper::rvi
