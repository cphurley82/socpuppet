#include "socpuppet/core/ucie_sideband.h"

#include <array>
#include <cstdint>
#include <optional>
#include <span>
#include <vector>

#include <gtest/gtest.h>

#include "socpuppet/core/little_endian.h"

namespace socpuppet {

// A packet with a different value in each field, so that a field encoded
// into the wrong place shows up.
SidebandPacket ADistinctivePacket() {
  return {.opcode = SidebandOpcode::kMessageWith64bData,
          .srcid = SidebandAgent::kD2dAdapter,
          .dstid = SidebandAgent::kPhysicalLayer,
          .msgcode = 0xA5,
          .msgsubcode = 0x02,
          .msginfo = 0x1234,
          .control_parity = true,
          .data_parity = false,
          .data = 0x0123'4567'89AB'CDEF};
}

TEST(WhenASidebandPacketIsEncoded, EachFieldIsWhereUcieHasIt) {
  // opcode [4:0], msgcode [21:14], srcid [31:29], msgsubcode [39:32],
  // msginfo [55:40], dstid [58:56], cp [62], dp [63].
  const std::vector<std::uint8_t> bytes = ADistinctivePacket().Encode();

  EXPECT_EQ(LoadLittleEndian<std::uint64_t>(bytes), 0x4212'3402'2029'401BU);
}

TEST(WhenASidebandPacketIsEncoded, ItsDataFollowsTheHeader) {
  const std::vector<std::uint8_t> bytes = ADistinctivePacket().Encode();

  EXPECT_EQ(LoadLittleEndian<std::uint64_t>(std::span{bytes}.subspan(8)),
            0x0123'4567'89AB'CDEFU);
}

// The same packet, carrying whatever `opcode` says it carries.
std::vector<std::uint8_t> EncodedWith(SidebandOpcode opcode) {
  SidebandPacket packet = ADistinctivePacket();
  packet.opcode = opcode;
  return packet.Encode();
}

TEST(WhenASidebandPacketIsEncoded, ItIsAsLongAsItsOpcodeSays) {
  // The header is eight bytes, and the data is what the opcode names.
  EXPECT_EQ(EncodedWith(SidebandOpcode::kMessageWithoutData).size(), 8U);
  EXPECT_EQ(EncodedWith(SidebandOpcode::kCompletionWith32bData).size(), 12U);
  EXPECT_EQ(EncodedWith(SidebandOpcode::kMessageWith64bData).size(), 16U);
}

TEST(WhenASidebandPacketGoesThereAndBack, EveryFieldComesBackWhole) {
  const SidebandPacket packet = ADistinctivePacket();

  EXPECT_EQ(SidebandPacket::Decode(packet.Encode()), packet);
}

TEST(WhenASidebandPacketCarriesOnly32BitsOfData, OnlyThoseGoAndComeBack) {
  SidebandPacket packet = ADistinctivePacket();
  packet.opcode = SidebandOpcode::kCompletionWith32bData;

  const std::optional<SidebandPacket> there_and_back =
      SidebandPacket::Decode(packet.Encode());

  packet.data = 0x89AB'CDEF;  // the four bytes that had room to travel
  EXPECT_EQ(there_and_back, packet);
}

TEST(WhenFewerBytesArriveOnTheSidebandThanAHeader, TheyAreNoPacket) {
  const std::vector<std::uint8_t> too_short(7, 0xFF);

  EXPECT_EQ(SidebandPacket::Decode(too_short), std::nullopt);
}

TEST(WhenTheBytesOnTheSidebandAreALengthNoOpcodeHas, TheyAreNoPacket) {
  std::vector<std::uint8_t> one_too_many =
      EncodedWith(SidebandOpcode::kMessageWithoutData);
  one_too_many.push_back(0xFF);

  EXPECT_EQ(SidebandPacket::Decode(one_too_many), std::nullopt);
}

TEST(WhenAnOpcodeArrivesOnTheSidebandThatUcieDoesNotAssign, ItIsNoPacket) {
  // 0b01111 is in none of the published tables, so there is no saying how
  // long the packet would be.
  const std::array<std::uint8_t, 8> unassigned =
      LittleEndianBytes(std::uint64_t{0b0'1111});

  EXPECT_EQ(SidebandPacket::Decode(unassigned), std::nullopt);
}

TEST(WhenANamedSidebandMessageIsPutInAPacket, ItCarriesUciesCodesForIt) {
  const SidebandPacket packet =
      MessagePacket(kSbinitDoneRequest, SidebandAgent::kD2dAdapter,
                    SidebandAgent::kPhysicalLayer);

  EXPECT_EQ(packet,
            (SidebandPacket{.opcode = SidebandOpcode::kMessageWithoutData,
                            .srcid = SidebandAgent::kD2dAdapter,
                            .dstid = SidebandAgent::kPhysicalLayer,
                            .msgcode = 0x95,
                            .msgsubcode = 0x01}));
}

TEST(WhenANamedSidebandMessageHasSomethingToSay, ItsPacketHasRoomForIt) {
  const SidebandPacket packet = MessagePacket(
      kMbinitParamConfigurationRequest, SidebandAgent::kD2dAdapter,
      SidebandAgent::kD2dAdapter, 0x0123'4567'89AB'CDEF);

  EXPECT_EQ(packet,
            (SidebandPacket{.opcode = SidebandOpcode::kMessageWith64bData,
                            .srcid = SidebandAgent::kD2dAdapter,
                            .dstid = SidebandAgent::kD2dAdapter,
                            .msgcode = 0xA5,
                            .msgsubcode = 0x00,
                            .data = 0x0123'4567'89AB'CDEF}));
}

}  // namespace socpuppet
