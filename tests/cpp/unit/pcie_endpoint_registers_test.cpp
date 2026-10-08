#include "socpuppet/core/pcie_endpoint_registers.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>

namespace socpuppet {

namespace {

using ::testing::ElementsAre;
using Owner = PcieEndpointRegisters::Owner;

// Offsets in configuration space.
constexpr std::uint64_t kIds = 0x00;
constexpr std::uint64_t kCommand = 0x04;
constexpr std::uint64_t kBar0 = 0x10;
constexpr std::uint64_t kEndOfConfigurationSpace = 0x1000;

// An endpoint for a function with 0x2000 bytes of registers and two
// interrupt vectors, placed at `base` with memory decoding on.
PcieEndpointRegisters PlacedAt(std::uint32_t base) {
  PcieEndpointRegisters registers{
      {.vendor_id = 0x5350, .device_id = 0xC0DE, .class_code = 0x010802},
      /*function_size=*/0x2000,
      /*vectors=*/2};
  const std::array<std::uint8_t, 4> place{
      static_cast<std::uint8_t>(base), static_cast<std::uint8_t>(base >> 8),
      static_cast<std::uint8_t>(base >> 16),
      static_cast<std::uint8_t>(base >> 24)};
  registers.WriteConfiguration(kBar0, place);
  // Memory decoding is bit 1 of the command register.
  registers.WriteConfiguration(kCommand, std::array<std::uint8_t, 2>{0x02, 0});
  return registers;
}

// Walks the list of capabilities as a host does, and returns their
// identifiers in the order it meets them. The list starts at the offset in
// the register at 0x34, and each capability begins with its identifier
// and the offset of the next, which is zero after the last.
std::vector<std::uint8_t> CapabilitiesOf(
    const PcieEndpointRegisters& registers) {
  constexpr std::uint64_t kFirstCapability = 0x34;
  // More than fit in configuration space: a list that loops ends here.
  constexpr std::size_t kTooMany = 64;
  std::vector<std::uint8_t> identifiers;
  std::array<std::uint8_t, 1> next{};
  registers.ReadConfiguration(kFirstCapability, next);
  while (next[0] != 0 && identifiers.size() < kTooMany) {
    std::array<std::uint8_t, 2> header{};
    registers.ReadConfiguration(next[0], header);
    identifiers.push_back(header[0]);
    next[0] = header[1];
  }
  return identifiers;
}

// Capability identifiers.
constexpr std::uint8_t kPowerManagement = 0x01;
constexpr std::uint8_t kMsix = 0x11;

}  // namespace

TEST(WhenAnEndpointIsMade, ItsOneCapabilityIsMsix) {
  const PcieEndpointRegisters registers = PlacedAt(0x4001'0000);

  EXPECT_THAT(CapabilitiesOf(registers), ElementsAre(kMsix));
}

TEST(WhenACapabilityIsAdded, TheHostFindsItAfterMsix) {
  PcieEndpointRegisters registers = PlacedAt(0x4001'0000);

  registers.AddCapability(kPowerManagement,
                          std::array<std::uint8_t, 2>{0x03, 0x00});

  EXPECT_THAT(CapabilitiesOf(registers), ElementsAre(kMsix, kPowerManagement));
}

TEST(WhenACapabilityIsAdded, TheHostReadsItsRegistersAfterItsHeader) {
  PcieEndpointRegisters registers = PlacedAt(0x4001'0000);

  const std::uint64_t offset = registers.AddCapability(
      kPowerManagement, std::array<std::uint8_t, 2>{0x03, 0x5A});

  std::array<std::uint8_t, 2> after_the_header{};
  registers.ReadConfiguration(offset + 2, after_the_header);
  EXPECT_THAT(after_the_header, ElementsAre(0x03, 0x5A));
}

TEST(WhenTheHostWritesToAnAddedCapability, ItKeepsItsValues) {
  PcieEndpointRegisters registers = PlacedAt(0x4001'0000);
  const std::uint64_t offset = registers.AddCapability(
      kPowerManagement, std::array<std::uint8_t, 2>{0x03, 0x5A});

  registers.WriteConfiguration(
      offset, std::array<std::uint8_t, 4>{0xFF, 0xFF, 0xFF, 0xFF});

  EXPECT_THAT(CapabilitiesOf(registers), ElementsAre(kMsix, kPowerManagement));
  std::array<std::uint8_t, 2> after_the_header{};
  registers.ReadConfiguration(offset + 2, after_the_header);
  EXPECT_THAT(after_the_header, ElementsAre(0x03, 0x5A));
}

TEST(WhenTheHostWritesToTheIds, TheyKeepTheirValues) {
  PcieEndpointRegisters registers = PlacedAt(0x4001'0000);

  registers.WriteConfiguration(
      kIds, std::array<std::uint8_t, 4>{0xFF, 0xFF, 0xFF, 0xFF});

  std::array<std::uint8_t, 4> ids{};
  registers.ReadConfiguration(kIds, ids);
  EXPECT_EQ(ids, (std::array<std::uint8_t, 4>{0x50, 0x53, 0xDE, 0xC0}));
}

TEST(WhenAReadStartsPastTheEndOfConfigurationSpace, ItReadsAsZeros) {
  const PcieEndpointRegisters registers = PlacedAt(0x4001'0000);
  std::array<std::uint8_t, 4> beyond{0xAA, 0xAA, 0xAA, 0xAA};

  registers.ReadConfiguration(kEndOfConfigurationSpace, beyond);

  EXPECT_EQ(beyond, (std::array<std::uint8_t, 4>{0, 0, 0, 0}));
}

TEST(WhenAnAccessStartsInTheFunctionsRegistersAndRunsIntoTheTable,
     ItIsNobodys) {
  // The function's registers end at 0x2000, where the MSI-X table begins.
  const PcieEndpointRegisters registers = PlacedAt(0x4001'0000);

  EXPECT_EQ(registers.Decode(0x4001'0000 + 0x1FFE, 4).owner, Owner::kNobody);
}

TEST(WhenAnAccessIsBelowWhereBar0Points, ItIsNobodys) {
  const PcieEndpointRegisters registers = PlacedAt(0x4001'0000);

  EXPECT_EQ(registers.Decode(0x4000'FFFC, 4).owner, Owner::kNobody);
}

}  // namespace socpuppet
