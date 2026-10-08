#include "socpuppet/core/pcie_endpoint_registers.h"

#include <algorithm>
#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <stdexcept>
#include <vector>

namespace socpuppet {

namespace {

constexpr std::uint64_t kPage = 0x1000;

// Offsets in configuration space, and bits in the registers there.
constexpr std::size_t kVendorId = 0x00;
constexpr std::size_t kDeviceId = 0x02;
constexpr std::size_t kCommand = 0x04;
constexpr std::uint16_t kMemoryDecoding = 1U << 1;
constexpr std::uint16_t kBusMastering = 1U << 2;
constexpr std::size_t kStatus = 0x06;
constexpr std::uint16_t kHasCapabilities = 1U << 4;
constexpr std::uint16_t kReceivedMasterAbort = 1U << 13;
constexpr std::size_t kRevisionAndClass = 0x08;
constexpr std::size_t kBar0 = 0x10;
constexpr std::uint64_t kBarKindBits = 0xF;
constexpr std::uint64_t k64BitMemoryBar = 0x4;
constexpr std::size_t kFirstCapability = 0x34;
// Capabilities end before the extended part of configuration space, which
// is laid out differently.
constexpr std::size_t kEndOfCapabilities = 0x100;
// A capability starts with its identifier and the offset of the next.
constexpr std::size_t kCapabilityHeader = 2;
constexpr std::size_t kNextCapability = 1;

// The MSI-X capability: its identifier, and its registers by their offset
// from its start.
constexpr std::uint8_t kMsixIdentifier = 0x11;
constexpr std::size_t kMsixControl = 2;
constexpr std::uint16_t kMsixEveryVectorMasked = 1U << 14;
constexpr std::uint16_t kMsixEnabled = 1U << 15;
constexpr std::size_t kMsixTable = 4;
constexpr std::size_t kMsixPending = 8;
// How long it is without its header.
constexpr std::size_t kMsixRegisters = 10;

std::uint64_t RoundUpToAPage(std::uint64_t size) {
  return (size + kPage - 1) / kPage * kPage;
}

// Whether `length` bytes at `offset` are wholly inside a region.
bool Inside(std::uint64_t offset, std::size_t length, std::uint64_t start,
            std::uint64_t size) {
  return offset >= start && offset - start <= size &&
         length <= size - (offset - start);
}

}  // namespace

PcieEndpointRegisters::PcieEndpointRegisters(const Identity& identity,
                                             std::uint64_t function_size,
                                             std::size_t vectors)
    : function_size_(function_size),
      table_(vectors),
      table_offset_(RoundUpToAPage(function_size)),
      pending_offset_(table_offset_ + RoundUpToAPage(table_.Size())) {
  Store(kVendorId, identity.vendor_id);
  Store(kDeviceId, identity.device_id);
  // The class code is the three bytes above the revision.
  Store(kRevisionAndClass, identity.class_code << 8);
  // The host may switch memory decoding and bus mastering on and off.
  LetTheHostWrite(kCommand, std::uint16_t{kMemoryDecoding | kBusMastering});
  // BAR0 is 64 bits wide, in two registers. Its low four bits say what
  // kind it is, and the host cannot change them: memory, 64-bit. Nor can
  // it change the address bits below the BAR's size, which stay zero.
  // Writing all ones and reading back therefore tells the host how big
  // the BAR is.
  // The size is a power of two with room for everything behind the BAR.
  const std::uint64_t bar0_size = std::bit_ceil(pending_offset_ + kPage);
  Store(kBar0, std::uint64_t{k64BitMemoryBar});
  LetTheHostWrite(kBar0, ~(bar0_size - 1));

  // The first capability is MSI-X.
  msix_ = AddCapability(kMsixIdentifier,
                        std::array<std::uint8_t, kMsixRegisters>{});
  // Its control register holds the table's size, counted from zero, and
  // two bits the host can write: on or off, and mask every vector.
  Store(msix_ + kMsixControl, static_cast<std::uint16_t>(vectors - 1));
  LetTheHostWrite(msix_ + kMsixControl,
                  std::uint16_t{kMsixEnabled | kMsixEveryVectorMasked});
  // And where the table and the pending bits are: behind BAR0 (the low
  // three bits, which are zero), at these offsets.
  Store(msix_ + kMsixTable, static_cast<std::uint32_t>(table_offset_));
  Store(msix_ + kMsixPending, static_cast<std::uint32_t>(pending_offset_));
}

std::size_t PcieEndpointRegisters::AddCapability(
    std::uint8_t identifier, std::span<const std::uint8_t> registers) {
  const std::size_t offset = next_capability_;
  if (offset + kCapabilityHeader + registers.size() > kEndOfCapabilities) {
    throw std::length_error(
        "There is no room in configuration space for another capability: "
        "they have to fit between 0x40 and 0x100.");
  }
  // The list is found through a status bit and the offset of its first
  // capability, and each capability names the next.
  if (last_capability_ == 0) {
    Store(kStatus, static_cast<std::uint16_t>(Load<std::uint16_t>(kStatus) |
                                              kHasCapabilities));
    Store(kFirstCapability, static_cast<std::uint8_t>(offset));
  } else {
    Store(last_capability_ + kNextCapability,
          static_cast<std::uint8_t>(offset));
  }
  Store(offset, identifier);
  std::ranges::copy(
      registers,
      std::span{configuration_}.subspan(offset + kCapabilityHeader).begin());
  last_capability_ = offset;
  // Capabilities start on a multiple of four bytes.
  next_capability_ =
      (offset + kCapabilityHeader + registers.size() + 3) / 4 * 4;
  return offset;
}

void PcieEndpointRegisters::ReadConfiguration(
    std::uint64_t offset, std::span<std::uint8_t> out) const {
  std::ranges::fill(out, std::uint8_t{0});
  if (offset >= configuration_.size()) return;
  const std::size_t length =
      std::min<std::uint64_t>(out.size(), configuration_.size() - offset);
  std::ranges::copy(std::span{configuration_}.subspan(offset, length),
                    out.begin());
}

void PcieEndpointRegisters::WriteConfiguration(
    std::uint64_t offset, std::span<const std::uint8_t> in) {
  for (std::size_t index = 0;
       index < in.size() && offset + index < configuration_.size(); ++index) {
    std::uint8_t& byte = configuration_[offset + index];
    const std::uint8_t writable = writable_[offset + index];
    byte =
        static_cast<std::uint8_t>((byte & ~writable) | (in[index] & writable));
  }
}

PcieEndpointRegisters::Landing PcieEndpointRegisters::Decode(
    std::uint64_t address, std::size_t length) const {
  if ((Load<std::uint16_t>(kCommand) & kMemoryDecoding) == 0) return {};
  const std::uint64_t base = Load<std::uint64_t>(kBar0) & ~kBarKindBits;
  if (address < base) return {};
  const std::uint64_t offset = address - base;
  if (Inside(offset, length, 0, function_size_)) {
    return {.owner = Owner::kFunction, .offset = offset};
  }
  if (Inside(offset, length, table_offset_, table_.Size())) {
    return {.owner = Owner::kTable, .offset = offset - table_offset_};
  }
  if (Inside(offset, length, pending_offset_, kPage)) {
    return {.owner = Owner::kPendingBits, .offset = offset - pending_offset_};
  }
  return {};
}

void PcieEndpointRegisters::ReadOwn(const Landing& landing,
                                    std::span<std::uint8_t> out) const {
  if (landing.owner == Owner::kTable) {
    table_.Read(landing.offset, out);
  } else {
    table_.ReadPendingBits(landing.offset, out);
  }
}

void PcieEndpointRegisters::WriteOwn(const Landing& landing,
                                     std::span<const std::uint8_t> in) {
  if (landing.owner == Owner::kTable) table_.Write(landing.offset, in);
}

bool PcieEndpointRegisters::IsBusMaster() const {
  return (Load<std::uint16_t>(kCommand) & kBusMastering) != 0;
}

std::optional<PcieEndpointRegisters::Message> PcieEndpointRegisters::Raise(
    std::size_t vector) {
  if (!MsixIsOn()) return {};
  if (!CanSend(vector)) {
    table_.SetPending(vector, true);
    return {};
  }
  return table_.MessageOf(vector);
}

void PcieEndpointRegisters::NoteMasterAbort() {
  Store(kStatus, static_cast<std::uint16_t>(Load<std::uint16_t>(kStatus) |
                                            kReceivedMasterAbort));
}

std::vector<PcieEndpointRegisters::Message>
PcieEndpointRegisters::TakePending() {
  std::vector<Message> messages;
  if (!MsixIsOn()) return messages;
  for (std::size_t vector = 0; vector < table_.Vectors(); ++vector) {
    if (table_.IsPending(vector) && CanSend(vector)) {
      table_.SetPending(vector, false);
      messages.push_back(table_.MessageOf(vector));
    }
  }
  return messages;
}

bool PcieEndpointRegisters::MsixIsOn() const {
  return (Load<std::uint16_t>(msix_ + kMsixControl) & kMsixEnabled) != 0;
}

bool PcieEndpointRegisters::CanSend(std::size_t vector) const {
  const bool every_vector_masked =
      (Load<std::uint16_t>(msix_ + kMsixControl) & kMsixEveryVectorMasked) != 0;
  return IsBusMaster() && !every_vector_masked && !table_.IsMasked(vector);
}

}  // namespace socpuppet
