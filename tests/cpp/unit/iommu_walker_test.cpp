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
constexpr iommu_request kSomeRead{.device_id = 0x21, .iova = 0x8000'1234};

// The same read, by `device_id`.
constexpr iommu_request SomeReadBy(std::uint32_t device_id) {
  iommu_request read = kSomeRead;
  read.device_id = device_id;
  return read;
}

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

}  // namespace vpvper::rvi
