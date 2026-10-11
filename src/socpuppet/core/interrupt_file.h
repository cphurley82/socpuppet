#ifndef SOCPUPPET_CORE_INTERRUPT_FILE_H_
#define SOCPUPPET_CORE_INTERRUPT_FILE_H_

#include <bit>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

namespace socpuppet {

// An interrupt file: what one hart's IMSIC keeps for one privilege mode.
//
// An IMSIC (incoming message-signalled interrupt controller) is the part
// of RISC-V's Advanced Interrupt Architecture that belongs to a hart. A
// device interrupts by sending a message, which is a number, an interrupt
// identity, and the file remembers which identities are pending. Firmware
// says which it wants to hear of, and takes them one at a time.
//
// This is the logic with no simulator attached. The model around it
// (models/imsic.h) gives it a page for messages to be written to, and the
// hart's registers to be reached through.
//
// What it leaves out: registers of 32 bits, which a 32-bit hart has twice
// as many of, and the other way of delivering the specification allows,
// from a PLIC.
class InterruptFile {
 public:
  // The file's registers, by the numbers the hart selects them with
  // (`miselect`, then `mireg`). They are the AIA specification's.
  //
  // Whether the file may interrupt its hart at all: 1 if so.
  static constexpr std::uint32_t kEidelivery = 0x70;
  // Identities at or above this one are held back. Zero holds nothing
  // back.
  static constexpr std::uint32_t kEithreshold = 0x72;
  // Which identities are pending, a bit each. This register has the first
  // 64, the one numbered two higher has the next 64, and so on.
  static constexpr std::uint32_t kEip0 = 0x80;
  // Which identities firmware wants to hear of, laid out the same way.
  static constexpr std::uint32_t kEie0 = 0xC0;

  // `identities` is the highest identity the file has. They start at 1.
  // The specification has a file end on 63, 127 and so on up to 2047, one
  // short of a whole register. Nothing here holds a caller to that.
  explicit InterruptFile(std::uint32_t identities)
      : has_((identities / kBitsInARegister) + 1),
        pending_(has_.size()),
        enabled_(has_.size()) {
    for (std::uint32_t identity = 1; identity <= identities; ++identity) {
      has_[identity / kBitsInARegister] |= BitOf(identity);
    }
  }

  // A message has arrived: `identity` is pending until it is claimed. A
  // message that names no identity of the file's is dropped.
  void Deliver(std::uint32_t identity) {
    const std::size_t index = identity / kBitsInARegister;
    if (index < has_.size()) pending_[index] |= BitOf(identity) & has_[index];
  }

  // Reads one of the file's registers. With none of that number there is
  // nothing to read, and a hart that tried takes an illegal-instruction
  // trap.
  std::optional<std::uint64_t> Read(std::uint32_t reg) const {
    if (reg == kEidelivery) return delivering_ ? 1 : 0;
    if (reg == kEithreshold) return threshold_;
    if (IsReserved(reg)) return 0;
    if (const auto index = IndexFrom(kEip0, reg)) return Word(pending_, *index);
    if (const auto index = IndexFrom(kEie0, reg)) return Word(enabled_, *index);
    return std::nullopt;
  }

  // Writes one of the file's registers. Returns whether there is one of
  // that number, as for Read.
  bool Write(std::uint32_t reg, std::uint64_t value) {
    if (reg == kEidelivery) {
      delivering_ = (value & 1) != 0;
    } else if (reg == kEithreshold) {
      threshold_ = value;
    } else if (IsReserved(reg)) {
      // Kept for the specification's later use: a write does nothing.
    } else if (const auto of_pending = IndexFrom(kEip0, reg)) {
      SetWord(pending_, *of_pending, value);
    } else if (const auto of_enables = IndexFrom(kEie0, reg)) {
      SetWord(enabled_, *of_enables, value);
    } else {
      return false;
    }
    return true;
  }

  // The identity firmware should see to next: the lowest that is pending
  // and enabled, since a lower identity has the higher priority, if it is
  // below the threshold. Zero if there is none. Whether delivery is
  // switched on makes no difference to it.
  //
  // This is the bare identity. The hart's register for it (`mtopei`) has
  // it twice over, shifted, which is for whoever answers that register to
  // lay out.
  std::uint32_t Top() const {
    for (std::size_t index = 0; index < pending_.size(); ++index) {
      const std::uint64_t waiting = pending_[index] & enabled_[index];
      if (waiting == 0) continue;
      const std::uint32_t lowest =
          (static_cast<std::uint32_t>(index) * kBitsInARegister) +
          static_cast<std::uint32_t>(std::countr_zero(waiting));
      return threshold_ != 0 && lowest >= threshold_ ? 0 : lowest;
    }
    return 0;
  }

  // Takes the top: it is no longer pending. Returns it, or zero if there
  // was none. This is what a handler does first, to learn which identity
  // it was woken for.
  std::uint32_t Claim() {
    const std::uint32_t top = Top();
    if (top != 0) pending_[top / kBitsInARegister] &= ~BitOf(top);
    return top;
  }

  // Whether the file is asking for its hart's attention.
  bool Interrupting() const { return delivering_ && Top() != 0; }

 private:
  static constexpr std::uint32_t kBitsInARegister = 64;
  // How many registers there are of pending bits, and of enables: the
  // specification leaves 64 numbers for each kind, and with registers of
  // 64 bits every other one of them exists.
  static constexpr std::uint32_t kRegistersOfAKind = 32;

  static std::uint64_t BitOf(std::uint32_t identity) {
    return std::uint64_t{1} << (identity % kBitsInARegister);
  }

  // The numbers the specification keeps for itself among the first few.
  // They read as zero.
  static bool IsReserved(std::uint32_t reg) {
    return reg == 0x71 || (reg >= 0x73 && reg <= 0x7F);
  }

  // Which of the registers that start at `first` the one numbered `reg`
  // is, if it is one of them. They are numbered in twos.
  static std::optional<std::size_t> IndexFrom(std::uint32_t first,
                                              std::uint32_t reg) {
    if (reg < first || reg >= first + (2 * kRegistersOfAKind)) {
      return std::nullopt;
    }
    if ((reg - first) % 2 != 0) return std::nullopt;
    return (reg - first) / 2;
  }

  // A register past the file's last identity reads as zero.
  static std::uint64_t Word(const std::vector<std::uint64_t>& words,
                            std::size_t index) {
    return index < words.size() ? words[index] : 0;
  }

  // Only the bits of identities the file has can be set, so a write to a
  // register past its last identity does nothing.
  void SetWord(std::vector<std::uint64_t>& words, std::size_t index,
               std::uint64_t value) const {
    if (index < words.size()) words[index] = value & has_[index];
  }

  bool delivering_ = false;
  std::uint64_t threshold_ = 0;
  // A bit for each identity, 64 to a word, as the registers have them:
  // which identities the file has, which are pending and which firmware
  // wants to hear of.
  std::vector<std::uint64_t> has_;
  std::vector<std::uint64_t> pending_;
  std::vector<std::uint64_t> enabled_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_INTERRUPT_FILE_H_
