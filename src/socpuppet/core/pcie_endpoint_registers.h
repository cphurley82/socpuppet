#ifndef SOCPUPPET_CORE_PCIE_ENDPOINT_REGISTERS_H_
#define SOCPUPPET_CORE_PCIE_ENDPOINT_REGISTERS_H_

#include <algorithm>
#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <vector>

namespace socpuppet {

// The registers of a PCIe endpoint, and the decisions that hang on them,
// with no simulator attached.
//
// An endpoint is the part of a device that the PCIe bus sees. It has three
// jobs here.
//
//   - Its configuration space says who made the device and what kind of
//     thing it is, which is how a host finds a driver for it.
//   - Its base address register (BAR) is how the device asks for a piece
//     of the host's address map and how the host says where it has put it.
//     This endpoint has one, the first. Behind it are the registers of the
//     function the endpoint fronts for, and after those the endpoint's own
//     MSI-X table.
//   - MSI-X is how the device interrupts. There is no wire to the host.
//     The host writes into the table, for each interrupt vector, an
//     address and 32 bits of data, and the device interrupts by writing
//     that data to that address.
//
//   BAR0:  ┌────────────────────────┐ 0
//          │ the function's own     │
//          │ registers              │
//          ├────────────────────────┤ MSI-X table: 16 bytes per vector
//          ├────────────────────────┤ pending bits: one per vector
//          └────────────────────────┘
//
// An interrupt is the rise of one of the function's lines. One that cannot
// be sent yet (its vector is masked, say) is remembered as pending and sent
// when it can be. It stays pending even if the line has fallen again by
// then, where real hardware would forget it, so a driver that masks a
// vector, clears the cause by hand and unmasks gets one message more than
// it would from a real device.
//
// The layout is written from public descriptions of it (the register
// definitions in Zephyr's include/zephyr/drivers/pcie/pcie.h and msi.h
// among them), since the PCI specifications themselves are not free to
// read. It makes no claim to conform to them.
class PcieEndpointRegisters {
 public:
  // What the endpoint says it is.
  struct Identity {
    // Who made it, and which of their devices it is.
    std::uint16_t vendor_id = 0;
    std::uint16_t device_id = 0;
    // What kind of device it is, as three bytes: class, subclass and
    // programming interface. An NVMe drive is 01, 08, 02.
    std::uint32_t class_code = 0;
  };

  // An interrupt, as it travels: a write of `data` to `address`.
  struct Message {
    std::uint64_t address = 0;
    std::uint32_t data = 0;
    bool operator==(const Message&) const = default;
  };

  // What a memory access on the host's bus is for.
  enum class Owner {
    // Not this device: memory decoding is off, or the access is not
    // wholly inside one part of where BAR0 points.
    kNobody,
    // The function's register block.
    kFunction,
    // The endpoint's own MSI-X table, and its pending bits.
    kTable,
    kPendingBits,
  };
  struct Landing {
    Owner owner = Owner::kNobody;
    // How far into that part the access starts.
    std::uint64_t offset = 0;
  };

  // `function_size` is how many bytes the function's register block takes,
  // and `vectors` how many interrupt vectors it has.
  PcieEndpointRegisters(const Identity& identity, std::uint64_t function_size,
                        std::size_t vectors)
      : function_size_(function_size),
        table_offset_(RoundUpToAPage(function_size)),
        pending_offset_(table_offset_ +
                        RoundUpToAPage(vectors * kTableEntrySize)),
        table_(vectors * kTableEntrySize),
        pending_(vectors) {
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
    // Features beyond the basics are capabilities, in a linked list that a
    // host walks: a status bit says there is one, a register says where
    // the first is, and each starts with its identifier and the offset of
    // the next. Here there is one, MSI-X.
    Store(kStatus, std::uint16_t{kHasCapabilities});
    Store(kFirstCapability, std::uint8_t{kMsix});
    Store(kMsix, std::uint8_t{kMsixIdentifier});
    // Its control register holds the table's size, counted from zero, and
    // two bits the host can write: on or off, and mask every vector.
    Store(kMsixControl, static_cast<std::uint16_t>(vectors - 1));
    LetTheHostWrite(kMsixControl,
                    std::uint16_t{kMsixEnabled | kMsixEveryVectorMasked});
    // And where the table and the pending bits are: behind BAR0 (the low
    // three bits, which are zero), at these offsets.
    Store(kMsixTable, static_cast<std::uint32_t>(table_offset_));
    Store(kMsixPending, static_cast<std::uint32_t>(pending_offset_));
    // Every vector starts out masked: the mask bit is the lowest bit of
    // the fourth word of its table entry.
    for (std::size_t vector = 0; vector < vectors; ++vector) {
      table_[(vector * kTableEntrySize) + kEntryControl] = kEntryMasked;
    }
  }

  // Reads from configuration space. Whatever is past its end reads as
  // zeros.
  void ReadConfiguration(std::uint64_t offset,
                         std::span<std::uint8_t> out) const {
    std::ranges::fill(out, std::uint8_t{0});
    if (offset >= configuration_.size()) return;
    const std::size_t length =
        std::min<std::uint64_t>(out.size(), configuration_.size() - offset);
    std::ranges::copy(std::span{configuration_}.subspan(offset, length),
                      out.begin());
  }

  // Writes to configuration space. Only the bits the host is allowed to
  // change take the new value, and a write past the end changes nothing.
  void WriteConfiguration(std::uint64_t offset,
                          std::span<const std::uint8_t> in) {
    for (std::size_t index = 0;
         index < in.size() && offset + index < configuration_.size(); ++index) {
      std::uint8_t& byte = configuration_[offset + index];
      const std::uint8_t writable = writable_[offset + index];
      byte = static_cast<std::uint8_t>((byte & ~writable) |
                                       (in[index] & writable));
    }
  }

  // What a memory access on the host's bus is for, and where in it.
  Landing Decode(std::uint64_t address, std::size_t length) const {
    if ((Load<std::uint16_t>(kCommand) & kMemoryDecoding) == 0) return {};
    const std::uint64_t base = Load<std::uint64_t>(kBar0) & ~kBarKindBits;
    if (address < base) return {};
    const std::uint64_t offset = address - base;
    if (Inside(offset, length, 0, function_size_)) {
      return {.owner = Owner::kFunction, .offset = offset};
    }
    if (Inside(offset, length, table_offset_, table_.size())) {
      return {.owner = Owner::kTable, .offset = offset - table_offset_};
    }
    if (Inside(offset, length, pending_offset_, kPage)) {
      return {.owner = Owner::kPendingBits, .offset = offset - pending_offset_};
    }
    return {};
  }

  // Reads and writes of the endpoint's own registers behind BAR0, where
  // Decode() said an access lands: the MSI-X table, which the host fills
  // in, and the pending bits, which it can only read.
  void ReadOwn(const Landing& landing, std::span<std::uint8_t> out) const {
    if (landing.owner == Owner::kTable) {
      std::ranges::copy(std::span{table_}.subspan(landing.offset, out.size()),
                        out.begin());
      return;
    }
    // One bit for each vector, lowest first.
    for (std::size_t index = 0; index < out.size(); ++index) {
      std::uint8_t byte = 0;
      for (std::size_t bit = 0; bit < 8; ++bit) {
        const std::size_t vector = ((landing.offset + index) * 8) + bit;
        if (vector < pending_.size() && pending_[vector]) {
          byte = static_cast<std::uint8_t>(byte | (1U << bit));
        }
      }
      out[index] = byte;
    }
  }

  void WriteOwn(const Landing& landing, std::span<const std::uint8_t> in) {
    if (landing.owner != Owner::kTable) return;
    std::ranges::copy(in, std::span{table_}.subspan(landing.offset).begin());
  }

  // Whether the device may start accesses of its own, towards the host:
  // DMA, and interrupts sent as messages. It may not until the host says
  // so, by setting the bus-master bit of the command register.
  bool IsBusMaster() const {
    return (Load<std::uint16_t>(kCommand) & kBusMastering) != 0;
  }

  // The function's interrupt line for `vector` has risen. Returns the
  // message to send now, if it can be sent now. With MSI-X off there is no
  // interrupt at all. With it on but the vector masked, or the device not
  // yet a bus master, the vector is remembered as pending instead.
  std::optional<Message> Raise(std::size_t vector) {
    if (!MsixIsOn()) return {};
    if (!CanSend(vector)) {
      pending_[vector] = true;
      return {};
    }
    return MessageOf(vector);
  }

  // An access the endpoint started was answered by nobody, which the bus
  // calls a master abort. The status register says so from then on: a
  // real device lets the host clear the bit by writing a one to it, and
  // this one does not yet.
  void NoteMasterAbort() {
    Store(kStatus, static_cast<std::uint16_t>(Load<std::uint16_t>(kStatus) |
                                              kReceivedMasterAbort));
  }

  // The messages of pending vectors that can be sent now, which are then
  // no longer pending. Worth asking after any write from the host, since
  // that is what unmasks a vector.
  std::vector<Message> TakePending() {
    std::vector<Message> messages;
    if (!MsixIsOn()) return messages;
    for (std::size_t vector = 0; vector < pending_.size(); ++vector) {
      if (pending_[vector] && CanSend(vector)) {
        pending_[vector] = false;
        messages.push_back(MessageOf(vector));
      }
    }
    return messages;
  }

 private:
  static constexpr std::uint64_t kPage = 0x1000;

  // Offsets in configuration space, and bits in the registers there.
  static constexpr std::size_t kVendorId = 0x00;
  static constexpr std::size_t kDeviceId = 0x02;
  static constexpr std::size_t kCommand = 0x04;
  static constexpr std::uint16_t kMemoryDecoding = 1U << 1;
  static constexpr std::uint16_t kBusMastering = 1U << 2;
  static constexpr std::size_t kStatus = 0x06;
  static constexpr std::uint16_t kHasCapabilities = 1U << 4;
  static constexpr std::uint16_t kReceivedMasterAbort = 1U << 13;
  static constexpr std::size_t kRevisionAndClass = 0x08;
  static constexpr std::size_t kBar0 = 0x10;
  static constexpr std::uint64_t kBarKindBits = 0xF;
  static constexpr std::uint64_t k64BitMemoryBar = 0x4;
  static constexpr std::size_t kFirstCapability = 0x34;
  // The MSI-X capability, which is put straight after the standard part of
  // configuration space.
  static constexpr std::size_t kMsix = 0x40;
  static constexpr std::uint8_t kMsixIdentifier = 0x11;
  static constexpr std::size_t kMsixControl = kMsix + 2;
  static constexpr std::uint16_t kMsixEveryVectorMasked = 1U << 14;
  static constexpr std::uint16_t kMsixEnabled = 1U << 15;
  static constexpr std::size_t kMsixTable = kMsix + 4;
  static constexpr std::size_t kMsixPending = kMsix + 8;

  // An entry of the MSI-X table: the address in two halves, the data, and
  // a word whose lowest bit masks the vector.
  static constexpr std::size_t kTableEntrySize = 16;
  static constexpr std::size_t kEntryData = 8;
  static constexpr std::size_t kEntryControl = 12;
  static constexpr std::uint8_t kEntryMasked = 1U << 0;

  static std::uint64_t RoundUpToAPage(std::uint64_t size) {
    return (size + kPage - 1) / kPage * kPage;
  }

  // Whether `length` bytes at `offset` are wholly inside a region.
  static bool Inside(std::uint64_t offset, std::size_t length,
                     std::uint64_t start, std::uint64_t size) {
    return offset >= start && offset - start <= size &&
           length <= size - (offset - start);
  }

  bool MsixIsOn() const {
    return (Load<std::uint16_t>(kMsixControl) & kMsixEnabled) != 0;
  }

  bool CanSend(std::size_t vector) const {
    const bool every_vector_masked =
        (Load<std::uint16_t>(kMsixControl) & kMsixEveryVectorMasked) != 0;
    const bool masked = (table_[(vector * kTableEntrySize) + kEntryControl] &
                         kEntryMasked) != 0;
    return IsBusMaster() && !every_vector_masked && !masked;
  }

  Message MessageOf(std::size_t vector) const {
    const std::span entry =
        std::span{table_}.subspan(vector * kTableEntrySize, kTableEntrySize);
    return {.address = LoadFrom<std::uint64_t>(entry),
            .data = LoadFrom<std::uint32_t>(entry.subspan(kEntryData))};
  }

  // Stores a little-endian value in configuration space.
  template <typename Value>
  void Store(std::size_t offset, Value value) {
    for (std::size_t index = 0; index < sizeof(Value); ++index) {
      configuration_[offset + index] =
          static_cast<std::uint8_t>(value >> (8 * index));
    }
  }

  template <typename Value>
  Value Load(std::size_t offset) const {
    return LoadFrom<Value>(std::span{configuration_}.subspan(offset));
  }

  template <typename Value>
  static Value LoadFrom(std::span<const std::uint8_t> bytes) {
    Value value = 0;
    for (std::size_t index = 0; index < sizeof(Value); ++index) {
      value = static_cast<Value>(value | Value{bytes[index]} << (8 * index));
    }
    return value;
  }

  // Marks the bits of a register that a write from the host changes.
  template <typename Value>
  void LetTheHostWrite(std::size_t offset, Value bits) {
    for (std::size_t index = 0; index < sizeof(Value); ++index) {
      writable_[offset + index] =
          static_cast<std::uint8_t>(bits >> (8 * index));
    }
  }

  std::uint64_t function_size_;
  // Where the MSI-X table and the pending bits are behind BAR0, each
  // starting on a page of its own after the function's registers.
  std::uint64_t table_offset_;
  std::uint64_t pending_offset_;
  std::array<std::uint8_t, 0x1000> configuration_{};
  // Which bits of configuration space the host can change. The rest are
  // read-only.
  std::array<std::uint8_t, 0x1000> writable_{};
  // The MSI-X table as the host wrote it, and which vectors are pending.
  std::vector<std::uint8_t> table_;
  std::vector<bool> pending_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_PCIE_ENDPOINT_REGISTERS_H_
