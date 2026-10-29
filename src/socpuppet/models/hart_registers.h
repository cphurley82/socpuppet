#ifndef SOCPUPPET_MODELS_HART_REGISTERS_H_
#define SOCPUPPET_MODELS_HART_REGISTERS_H_

#include <cassert>
#include <cstdint>

namespace socpuppet {

// How a hart reaches registers of its own that another block keeps for it.
//
// 🎓 A hart's control and status registers (CSRs) are read and written
// with instructions of their own, and not over the bus. Most are inside
// the hart. RISC-V's Advanced Interrupt Architecture adds some that are
// really its interrupt controller's: an IMSIC's interrupt files have no
// registers on the bus at all, and firmware reaches them through the hart.
// On a chip that is wires between the two. Here it is a pair of ordinary
// TLM sockets, from the CPU to the block, and this says what an access on
// them means.
//
// An access is of eight bytes, the width of a 64-bit hart's registers.
// Its address says which register: the CSR's number, twelve bits up. Two
// of the CSRs are windows, `mireg` and `sireg`: firmware writes a number
// to `miselect` and then finds the register of that number at `mireg`. An
// access to a window has the number that was selected in its low twelve
// bits, which is as many bits of `miselect` or `siselect` as a hart here
// keeps. A block answers an address it has no register for with an
// address error, and the hart takes an illegal-instruction trap, as it
// does for a CSR it has not got.
//
// An instruction that reads a CSR and writes it, as a claim through
// `mtopei` does, is one act to firmware. Here it is a read and then a
// write. So a block never waits in an access, and a hart sends the two
// with no wait between them: nothing can then happen in the middle. The
// delay of an access means nothing and is left as it was.
//
// A hart's `time` register is also kept for it by another block, the
// machine timer, and is not carried this way: it has a socket of its own
// (models/machine_timer.h), whose one register needs no address and whose
// delay is how far ahead of the clock the hart has run.

// The CSRs an IMSIC answers, by their numbers, for machine mode and for
// supervisor mode: the window onto an interrupt file's registers, and the
// register that reads the file's top identity and, written, claims it.
inline constexpr std::uint32_t kMireg = 0x351;
inline constexpr std::uint32_t kMtopei = 0x35C;
inline constexpr std::uint32_t kSireg = 0x151;
inline constexpr std::uint32_t kStopei = 0x15C;
// The register that selects what machine mode's window looks at, and the
// one that does for supervisor mode's. They are the hart's own to keep:
// what was selected travels in the window's address, and an IMSIC has no
// register for either.
inline constexpr std::uint32_t kMiselect = 0x350;
inline constexpr std::uint32_t kSiselect = 0x150;

// How wide an access is.
inline constexpr unsigned kHartRegisterBytes = 8;
// The highest number a window's selecting register can hold.
inline constexpr std::uint32_t kWidestSelection = 0xFFF;

// The address of an access to the CSR numbered `csr`. `selected` is which
// register a window is looking at, of twelve bits, and zero for a CSR that
// is not one.
constexpr std::uint64_t HartRegisterAddress(std::uint32_t csr,
                                            std::uint32_t selected = 0) {
  assert(selected <= kWidestSelection);
  return (std::uint64_t{csr} << 12U) | selected;
}

// The two parts of such an address.
constexpr std::uint32_t CsrOf(std::uint64_t address) {
  return static_cast<std::uint32_t>(address >> 12U);
}
constexpr std::uint32_t SelectedBy(std::uint64_t address) {
  return static_cast<std::uint32_t>(address & kWidestSelection);
}

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_HART_REGISTERS_H_
