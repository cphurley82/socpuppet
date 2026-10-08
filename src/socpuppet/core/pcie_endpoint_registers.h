#ifndef SOCPUPPET_CORE_PCIE_ENDPOINT_REGISTERS_H_
#define SOCPUPPET_CORE_PCIE_ENDPOINT_REGISTERS_H_

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <vector>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/msix_table.h"

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
//   - MSI-X is how the device interrupts: by messages, which the host
//     sets up in a table (see msix_table.h).
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

  using Message = MsixTable::Message;

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
                        std::size_t vectors);

  // Gives the device one more capability, which the host finds at the end
  // of the list. 🎓 Features beyond the basics are capabilities, in a
  // linked list that a host walks: a status bit says there is one, a
  // register says where the first is, and each starts with its identifier
  // and the offset of the next.
  //
  // `registers` is what follows that two-byte header. The host can read it
  // and cannot change it. Returns the capability's offset in configuration
  // space.
  std::size_t AddCapability(std::uint8_t identifier,
                            std::span<const std::uint8_t> registers);

  // Reads from configuration space. Whatever is past its end reads as
  // zeros.
  void ReadConfiguration(std::uint64_t offset,
                         std::span<std::uint8_t> out) const;

  // Writes to configuration space. Only the bits the host is allowed to
  // change take the new value, and a write past the end changes nothing.
  void WriteConfiguration(std::uint64_t offset,
                          std::span<const std::uint8_t> in);

  // What a memory access on the host's bus is for, and where in it.
  Landing Decode(std::uint64_t address, std::size_t length) const;

  // Reads and writes of the endpoint's own registers behind BAR0, where
  // Decode() said an access lands: the MSI-X table, which the host fills
  // in, and the pending bits, which it can only read.
  void ReadOwn(const Landing& landing, std::span<std::uint8_t> out) const;
  void WriteOwn(const Landing& landing, std::span<const std::uint8_t> in);

  // Whether the device may start accesses of its own, towards the host:
  // DMA, and interrupts sent as messages. It may not until the host says
  // so, by setting the bus-master bit of the command register.
  bool IsBusMaster() const;

  // The function's interrupt line for `vector` has risen. Returns the
  // message to send now, if it can be sent now. With MSI-X off there is no
  // interrupt at all. With it on but the vector masked, or the device not
  // yet a bus master, the vector is remembered as pending instead.
  std::optional<Message> Raise(std::size_t vector);

  // An access the endpoint started was answered by nobody, which the bus
  // calls a master abort. The status register says so from then on: a
  // real device lets the host clear the bit by writing a one to it, and
  // this one does not yet.
  void NoteMasterAbort();

  // The messages of pending vectors that can be sent now, which are then
  // no longer pending. Worth asking after any write from the host, since
  // that is what unmasks a vector.
  std::vector<Message> TakePending();

 private:
  bool MsixIsOn() const;
  bool CanSend(std::size_t vector) const;

  // Stores a little-endian value in configuration space.
  template <typename Value>
  void Store(std::size_t offset, Value value) {
    StoreLittleEndian(value, std::span{configuration_}.subspan(offset));
  }

  template <typename Value>
  Value Load(std::size_t offset) const {
    return LoadLittleEndian<Value>(std::span{configuration_}.subspan(offset));
  }

  // Marks the bits of a register that a write from the host changes.
  template <typename Value>
  void LetTheHostWrite(std::size_t offset, Value bits) {
    StoreLittleEndian(bits, std::span{writable_}.subspan(offset));
  }

  std::uint64_t function_size_;
  MsixTable table_;
  // Where the MSI-X table and the pending bits are behind BAR0, each
  // starting on a page of its own after the function's registers.
  std::uint64_t table_offset_;
  std::uint64_t pending_offset_;
  std::array<std::uint8_t, 0x1000> configuration_{};
  // Which bits of configuration space the host can change. The rest are
  // read-only.
  std::array<std::uint8_t, 0x1000> writable_{};
  // Where the last capability in the list is, and where the next one
  // would go. They start straight after the standard part of
  // configuration space.
  std::size_t last_capability_ = 0;
  std::size_t next_capability_ = 0x40;
  // Where the MSI-X capability is in configuration space.
  std::size_t msix_ = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_PCIE_ENDPOINT_REGISTERS_H_
