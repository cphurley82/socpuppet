#ifndef SOCPUPPET_CORE_UCIE_SIDEBAND_H_
#define SOCPUPPET_CORE_UCIE_SIDEBAND_H_

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <vector>

#include "socpuppet/core/little_endian.h"

namespace socpuppet {

// UCIe's sideband: the narrow management channel that runs beside a
// die-to-die link's main data path (its "mainband"). It is up before the
// mainband is, and it is how the two dies agree to bring the mainband up
// and read each other's registers afterwards.
//
// A packet is a 64-bit header and, depending on its opcode, 0, 32 or 64
// bits of data. The field positions and codes here follow UCIe, as far as
// public sources say what they are: the Hot Chips 2023 UCIe tutorial and
// Berkeley's open uciedigital RTL. Nothing here comes from the
// specification, and none of it is a claim of compliance.

// What a packet is for.
enum class SidebandOpcode : std::uint8_t {
  // Reading and writing a register on the other die.
  kMemoryRead32b = 0b00000,
  kMemoryWrite32b = 0b00001,
  // The answer to one of those.
  kCompletionWithoutData = 0b10000,
  kCompletionWith32bData = 0b10001,
  kMessageWithoutData = 0b10010,
  kMessageWith64bData = 0b11011,
};

// Who a packet is from or to. UCIe gives each layer of each die an id;
// these are the two that appear in link bring-up.
enum class SidebandAgent : std::uint8_t {
  kD2dAdapter = 0b001,
  kPhysicalLayer = 0b010,
};

// A message, as UCIe names it: a code, a subcode, and whether it carries
// 64 bits with it. UCIe writes the pair in braces, and so do the comments
// here: {SBINIT Done Request} is 0x95 with subcode 0x01.
struct SidebandMessage {
  std::uint8_t code;
  std::uint8_t subcode;
  bool carries_data = false;

  bool operator==(const SidebandMessage&) const = default;
};

// The messages a link's two dies send each other. The first group brings
// the link up, each named for the state of link training it belongs to;
// after that come the ones that manage a link already trained, and the one
// that reports a failure.
//
// {SBINIT Out of Reset}, which tells the other side that this one has left
// reset and is training.
constexpr SidebandMessage kSbinitOutOfReset{.code = 0x91, .subcode = 0x00};
// {SBINIT Done Request}, which asks the other side to agree that the
// sideband is up, and its answer.
constexpr SidebandMessage kSbinitDoneRequest{.code = 0x95, .subcode = 0x01};
constexpr SidebandMessage kSbinitDoneResponse{.code = 0x9A, .subcode = 0x01};
// {MBINIT.PARAM configuration request}, which offers the other side what
// this one can do on the mainband, and its answer.
constexpr SidebandMessage kMbinitParamConfigurationRequest{
    .code = 0xA5, .subcode = 0x00, .carries_data = true};
constexpr SidebandMessage kMbinitParamConfigurationResponse{
    .code = 0xAA, .subcode = 0x00, .carries_data = true};
// {MBINIT.CAL Done request}, which says the mainband has been calibrated.
constexpr SidebandMessage kMbinitCalDoneRequest{.code = 0xA5, .subcode = 0x02};
constexpr SidebandMessage kMbinitCalDoneResponse{.code = 0xAA, .subcode = 0x02};
// Link management, between the two dies' adapters: asking for the link to
// be in use, saying it is, saying it has failed, and asking for it to be
// trained again.
constexpr SidebandMessage kLinkMgmtRdiRequestActive{.code = 0x01,
                                                    .subcode = 0x01};
constexpr SidebandMessage kLinkMgmtRdiResponseActive{.code = 0x02,
                                                     .subcode = 0x01};
constexpr SidebandMessage kLinkMgmtRdiRequestLinkError{.code = 0x01,
                                                       .subcode = 0x0A};
constexpr SidebandMessage kLinkMgmtRdiRequestRetrain{.code = 0x01,
                                                     .subcode = 0x0B};
// {ErrMsg Fatal}, which says the link has failed in a way nothing can be
// done about without training it again.
constexpr SidebandMessage kErrorMessageFatal{.code = 0x09, .subcode = 0x02};

// How a register access on the other die turned out. UCIe's own encoding
// for this is not in public sources, so these numbers are ours; they
// travel in the bits a message's code is in.
enum class SidebandStatus : std::uint8_t {
  kSuccess = 0,
  // There is no such register on the other die, or it is not writable.
  kUnsupportedRequest = 2,
};

struct SidebandPacket {
  // Every packet here is built with its fields named. These defaults are
  // so that a field left unnamed holds a value UCIe assigns, rather than a
  // zero that means nothing.
  SidebandOpcode opcode = SidebandOpcode::kMessageWithoutData;
  SidebandAgent srcid = SidebandAgent::kD2dAdapter;
  SidebandAgent dstid = SidebandAgent::kD2dAdapter;
  // A message is named by a code and a subcode, the pair UCIe writes as
  // {SBINIT Out of Reset}, with room for whatever else it has to carry.
  std::uint8_t msgcode = 0;
  std::uint8_t msgsubcode = 0;
  std::uint16_t msginfo = 0;
  // Parity over the header and over the data. Nothing here corrupts a
  // packet, so nothing checks them; they are carried so that a trace looks
  // like a capture.
  bool control_parity = false;
  bool data_parity = false;
  // The opcode decides how many of these bytes travel: none, the lowest
  // four, or all eight.
  std::uint64_t data = 0;

  bool operator==(const SidebandPacket&) const = default;

  // The packet as bytes, least significant byte of the header first. The
  // opcode has to be one UCIe assigns, which is the only kind there is a
  // length for.
  std::vector<std::uint8_t> Encode() const;
  // The packet those bytes are, or nothing if they are no packet: too few
  // for a header, an opcode UCIe does not assign, or a length that the
  // opcode does not have.
  static std::optional<SidebandPacket> Decode(
      std::span<const std::uint8_t> bytes);

 private:
  // One field of the header: the bit UCIe starts it at, and how wide it
  // is, so that the layout can be read against the published tables.
  struct Field {
    unsigned shift;
    unsigned width;

    constexpr std::uint64_t Mask() const {
      return (std::uint64_t{1} << width) - 1;
    }
    constexpr std::uint64_t Holding(std::uint64_t value) const {
      return (value & Mask()) << shift;
    }
    constexpr std::uint64_t In(std::uint64_t header) const {
      return (header >> shift) & Mask();
    }
  };

  static constexpr Field kOpcode{.shift = 0, .width = 5};
  static constexpr Field kMsgcode{.shift = 14, .width = 8};
  static constexpr Field kSrcid{.shift = 29, .width = 3};
  static constexpr Field kMsgsubcode{.shift = 32, .width = 8};
  static constexpr Field kMsginfo{.shift = 40, .width = 16};
  static constexpr Field kDstid{.shift = 56, .width = 3};
  static constexpr Field kControlParity{.shift = 62, .width = 1};
  static constexpr Field kDataParity{.shift = 63, .width = 1};

  static constexpr std::size_t kHeaderBytes = 8;

  // How many bytes of data the opcode carries, and so how long the whole
  // packet is: a packet's length is not written in it anywhere. Nothing,
  // if UCIe assigns that opcode no meaning.
  static std::optional<std::size_t> DataBytesOf(SidebandOpcode opcode);

  // The data a packet carries, from however many bytes it carries it in.
  static std::uint64_t DataIn(std::span<const std::uint8_t> bytes);
};

inline std::uint64_t SidebandPacket::DataIn(
    std::span<const std::uint8_t> bytes) {
  std::array<std::uint8_t, sizeof(std::uint64_t)> all{};
  std::ranges::copy(bytes, all.begin());
  return LoadLittleEndian<std::uint64_t>(all);
}

inline std::optional<std::size_t> SidebandPacket::DataBytesOf(
    SidebandOpcode opcode) {
  switch (opcode) {
    case SidebandOpcode::kMemoryRead32b:
    case SidebandOpcode::kCompletionWithoutData:
    case SidebandOpcode::kMessageWithoutData:
      return 0;
    case SidebandOpcode::kMemoryWrite32b:
    case SidebandOpcode::kCompletionWith32bData:
      return 4;
    case SidebandOpcode::kMessageWith64bData:
      return 8;
  }
  return std::nullopt;
}

inline std::vector<std::uint8_t> SidebandPacket::Encode() const {
  const std::uint64_t header =
      kOpcode.Holding(static_cast<std::uint8_t>(opcode)) |
      kMsgcode.Holding(msgcode) |
      kSrcid.Holding(static_cast<std::uint8_t>(srcid)) |
      kMsgsubcode.Holding(msgsubcode) | kMsginfo.Holding(msginfo) |
      kDstid.Holding(static_cast<std::uint8_t>(dstid)) |
      kControlParity.Holding(static_cast<std::uint64_t>(control_parity)) |
      kDataParity.Holding(static_cast<std::uint64_t>(data_parity));
  // Decode refuses an opcode UCIe does not assign, and nothing builds a
  // packet with one, so such a packet is a header and nothing more.
  const std::size_t data_bytes = DataBytesOf(opcode).value_or(0);
  std::vector<std::uint8_t> bytes(kHeaderBytes + data_bytes);
  StoreLittleEndian(header, std::span{bytes});
  // As many of the data's bytes as the opcode makes room for, which is
  // the lowest four of eight for a packet that carries 32 bits.
  const std::array<std::uint8_t, sizeof(data)> all = LittleEndianBytes(data);
  std::ranges::copy_n(all.begin(), static_cast<std::ptrdiff_t>(data_bytes),
                      bytes.begin() + kHeaderBytes);
  return bytes;
}

inline std::optional<SidebandPacket> SidebandPacket::Decode(
    std::span<const std::uint8_t> bytes) {
  if (bytes.size() < kHeaderBytes) return std::nullopt;
  const auto header = LoadLittleEndian<std::uint64_t>(bytes);
  const auto opcode = static_cast<SidebandOpcode>(kOpcode.In(header));
  const std::optional<std::size_t> data_bytes = DataBytesOf(opcode);
  if (!data_bytes || bytes.size() != kHeaderBytes + *data_bytes) {
    return std::nullopt;
  }
  return SidebandPacket{
      .opcode = opcode,
      .srcid = static_cast<SidebandAgent>(kSrcid.In(header)),
      .dstid = static_cast<SidebandAgent>(kDstid.In(header)),
      .msgcode = static_cast<std::uint8_t>(kMsgcode.In(header)),
      .msgsubcode = static_cast<std::uint8_t>(kMsgsubcode.In(header)),
      .msginfo = static_cast<std::uint16_t>(kMsginfo.In(header)),
      .control_parity = kControlParity.In(header) != 0,
      .data_parity = kDataParity.In(header) != 0,
      .data = DataIn(bytes.subspan(kHeaderBytes, *data_bytes))};
}

// The message a packet carries, for comparing with the named ones above.
inline SidebandMessage MessageIn(const SidebandPacket& packet) {
  return {.code = packet.msgcode,
          .subcode = packet.msgsubcode,
          .carries_data = packet.opcode == SidebandOpcode::kMessageWith64bData};
}

// A register access on the other die, and its answer, use the same header
// as a message with its fields read differently: the byte enables are
// where a message's code is, and a 24-bit address is where its subcode and
// information are. That is how UCIe fits a register access into the same
// 64 bits, and keeping it means one packet type for the whole sideband.
inline std::uint32_t AddressIn(const SidebandPacket& packet) {
  return packet.msgsubcode | (std::uint32_t{packet.msginfo} << 8);
}
inline SidebandStatus StatusIn(const SidebandPacket& packet) {
  return static_cast<SidebandStatus>(packet.msgcode);
}

// How much of an address a register access can carry: the 24 bits that
// fit where a message's subcode and information are.
constexpr std::uint32_t kLargestSidebandAddress = (1U << 24) - 1;

// The packet that reads or writes `address` on the other die. An address
// too big to travel is cut down to what fits, which is what arrives.
inline SidebandPacket RegisterAccessPacket(SidebandOpcode opcode,
                                           std::uint32_t address,
                                           SidebandAgent from, SidebandAgent to,
                                           std::uint32_t data = 0) {
  const std::uint32_t fits = address & kLargestSidebandAddress;
  return {.opcode = opcode,
          .srcid = from,
          .dstid = to,
          .msgsubcode = static_cast<std::uint8_t>(fits),
          .msginfo = static_cast<std::uint16_t>(fits >> 8),
          .data = data};
}

// The answer to one of those.
inline SidebandPacket CompletionPacket(SidebandStatus status,
                                       std::optional<std::uint32_t> data,
                                       SidebandAgent from, SidebandAgent to) {
  return {.opcode = data ? SidebandOpcode::kCompletionWith32bData
                         : SidebandOpcode::kCompletionWithoutData,
          .srcid = from,
          .dstid = to,
          .msgcode = static_cast<std::uint8_t>(status),
          .data = data.value_or(0)};
}

// The packet that carries `message` from one agent to another.
inline SidebandPacket MessagePacket(const SidebandMessage& message,
                                    SidebandAgent from, SidebandAgent to,
                                    std::uint64_t data = 0) {
  return {.opcode = message.carries_data ? SidebandOpcode::kMessageWith64bData
                                         : SidebandOpcode::kMessageWithoutData,
          .srcid = from,
          .dstid = to,
          .msgcode = message.code,
          .msgsubcode = message.subcode,
          .data = message.carries_data ? data : 0};
}

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_UCIE_SIDEBAND_H_
