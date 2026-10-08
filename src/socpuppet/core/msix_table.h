#ifndef SOCPUPPET_CORE_MSIX_TABLE_H_
#define SOCPUPPET_CORE_MSIX_TABLE_H_

#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

namespace socpuppet {

// A device's MSI-X table, with no simulator attached.
//
// MSI-X is how a PCIe device interrupts. There is no wire to the host. The
// host writes into this table, for each interrupt vector, an address and
// 32 bits of data, and the device interrupts by writing that data to that
// address. Each entry also has a bit that masks its vector. Beside the
// table are the pending bits, one per vector, for interrupts that could
// not be sent when they happened.
class MsixTable {
 public:
  // An interrupt, as it travels: a write of `data` to `address`.
  struct Message {
    std::uint64_t address = 0;
    std::uint32_t data = 0;
    bool operator==(const Message&) const = default;
  };

  // Every vector starts out masked.
  explicit MsixTable(std::size_t vectors);

  std::size_t Vectors() const { return pending_.size(); }
  // How many bytes the table takes up: 16 for each vector.
  std::size_t Size() const { return entries_.size(); }

  // The host's reads and writes of the table. The access must be inside
  // it.
  void Read(std::uint64_t offset, std::span<std::uint8_t> out) const;
  void Write(std::uint64_t offset, std::span<const std::uint8_t> in);
  // The host's reads of the pending bits, which it cannot write: one bit
  // for each vector, lowest first, and zeros after the last.
  void ReadPendingBits(std::uint64_t offset, std::span<std::uint8_t> out) const;

  // Whether the host has this vector masked.
  bool IsMasked(std::size_t vector) const;
  // What the host has asked to be sent for this vector.
  Message MessageOf(std::size_t vector) const;

  bool IsPending(std::size_t vector) const { return pending_[vector]; }
  void SetPending(std::size_t vector, bool pending) {
    pending_[vector] = pending;
  }

 private:
  // The table as the host wrote it, and which vectors are pending.
  std::vector<std::uint8_t> entries_;
  std::vector<bool> pending_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_MSIX_TABLE_H_
