#ifndef TESTS_CPP_SUPPORT_RISCV_PROGRAM_H_
#define TESTS_CPP_SUPPORT_RISCV_PROGRAM_H_

#include <cstddef>
#include <cstdint>
#include <vector>

// Just enough of a RISC-V assembler to write a CPU test's program by hand,
// so that the tests need no toolchain. Every instruction here is in the
// base integer set and is encoded the same for 32 and 64 bits.
namespace riscv {

using Word = std::uint32_t;
using Program = std::vector<Word>;

// Registers, by their number.
inline constexpr Word kZero = 0;
inline constexpr Word kT0 = 5;
inline constexpr Word kT1 = 6;
inline constexpr Word kT2 = 7;

// A signed immediate, cut down to the low `bits` bits of its encoding.
constexpr Word Field(std::int32_t value, unsigned bits) {
  return static_cast<Word>(value) & ((Word{1} << bits) - 1);
}

// rd = upper20 << 12. (On a 64-bit core the result is sign-extended, so
// this reaches addresses below 0x8000'0000 only.)
constexpr Word Lui(Word rd, Word upper20) {
  return (upper20 << 12) | (rd << 7) | 0x37;
}
// rd = the address of this instruction, plus upper20 << 12.
constexpr Word Auipc(Word rd, Word upper20) {
  return (upper20 << 12) | (rd << 7) | 0x17;
}
constexpr Word Addi(Word rd, Word rs1, std::int32_t immediate) {
  return (Field(immediate, 12) << 20) | (rs1 << 15) | (rd << 7) | 0x13;
}
constexpr Word Li(Word rd, std::int32_t immediate) {
  return Addi(rd, kZero, immediate);
}
// rd = rs1 shifted right by `amount` bits, with zeros coming in at the top.
// Only an amount below 32 is encoded the same for both word sizes.
constexpr Word Srli(Word rd, Word rs1, Word amount) {
  return (amount << 20) | (rs1 << 15) | (5 << 12) | (rd << 7) | 0x13;
}
// rd = rs1 shifted left by `amount` bits (fewer than 32, as for Srli).
constexpr Word Slli(Word rd, Word rs1, Word amount) {
  return (amount << 20) | (rs1 << 15) | (1 << 12) | (rd << 7) | 0x13;
}
// Store the low byte of rs2 at offset(rs1).
constexpr Word Sb(Word rs2, Word rs1, std::int32_t offset) {
  const Word immediate = Field(offset, 12);
  return ((immediate >> 5) << 25) | (rs2 << 20) | (rs1 << 15) |
         ((immediate & 0x1F) << 7) | 0x23;
}
// Store the low 32 bits of rs2 at offset(rs1).
constexpr Word Sw(Word rs2, Word rs1, std::int32_t offset) {
  return Sb(rs2, rs1, offset) | (2 << 12);
}
// Branch to pc + offset if rs1 and rs2 differ.
constexpr Word Bne(Word rs1, Word rs2, std::int32_t offset) {
  const Word immediate = Field(offset, 13);
  return ((immediate >> 12) << 31) | (((immediate >> 5) & 0x3F) << 25) |
         (rs2 << 20) | (rs1 << 15) | (1 << 12) |
         (((immediate >> 1) & 0xF) << 8) | (((immediate >> 11) & 1) << 7) |
         0x63;
}
// Jump to pc + offset, leaving the return address in rd.
constexpr Word Jal(Word rd, std::int32_t offset) {
  const Word immediate = Field(offset, 21);
  return ((immediate >> 20) << 31) | (((immediate >> 1) & 0x3FF) << 21) |
         (((immediate >> 11) & 1) << 20) | (((immediate >> 12) & 0xFF) << 12) |
         (rd << 7) | 0x6F;
}
// Set, in a control and status register, the bits that are set in rs1.
constexpr Word Csrs(Word csr, Word rs1) {
  return (csr << 20) | (rs1 << 15) | (2 << 12) | 0x73;
}
// Write rs1 to a control and status register.
constexpr Word Csrw(Word csr, Word rs1) {
  return (csr << 20) | (rs1 << 15) | (1 << 12) | 0x73;
}
// The control and status register that says which interrupts are enabled,
// and its bits for the machine timer and machine external interrupts.
inline constexpr Word kMie = 0x304;
inline constexpr Word kMachineTimerInterrupt = 7;
inline constexpr Word kMachineExternalInterrupt = 11;
// The status register, and its bit that switches interrupts on as a whole.
inline constexpr Word kMstatus = 0x300;
inline constexpr Word kInterruptsOn = 3;
// The register that holds the address a trap jumps to.
inline constexpr Word kMtvec = 0x305;
// Return from a trap handler to where the trap was taken.
inline constexpr Word kMret = 0x3020'0073;
// Wait for an interrupt.
inline constexpr Word kWfi = 0x1050'0073;

// How far past its first instruction a program leaves its result.
inline constexpr std::int32_t kResultOffset = 0x200;

// Sleep for ever: wait for an interrupt, and if one comes, wait again.
inline void AppendSleepForEver(Program& program) {
  program.push_back(kWfi);
  program.push_back(Jal(kZero, -4));
}

// A program that stores `value` as its result and then sleeps. It finds the
// place for the result from its own address, so it runs wherever it is
// loaded.
inline Program StoreByteThenSleep(std::uint8_t value) {
  Program program;
  program.push_back(Auipc(kT0, 0));
  program.push_back(Li(kT1, value));
  program.push_back(Sb(kT1, kT0, kResultOffset));
  AppendSleepForEver(program);
  return program;
}

// A program that fills a register with ones, shifts it right by `amount`
// bits (fewer than 32), stores the low byte of what is left as its result,
// and sleeps.
inline Program StoreAllOnesShiftedRightThenSleep(Word amount) {
  Program program;
  program.push_back(Auipc(kT0, 0));
  program.push_back(Li(kT1, -1));
  program.push_back(Srli(kT1, kT1, amount));
  program.push_back(Sb(kT1, kT0, kResultOffset));
  AppendSleepForEver(program);
  return program;
}

// A program that stores a word at `address` (a multiple of 4096 below
// 0x8000'0000), `times` times over, and then sleeps.
inline Program StoreWordThenSleep(std::uint64_t address, int times = 1) {
  Program program;
  program.push_back(Lui(kT0, static_cast<Word>(address >> 12)));
  for (int count = 0; count < times; ++count) {
    program.push_back(Sw(kZero, kT0, 0));
  }
  AppendSleepForEver(program);
  return program;
}

// A program that sleeps until the external interrupt line is high, then
// stores a word at `address` (as for StoreWordThenSleep) and sleeps again.
//
// It enables the interrupt but leaves interrupts as a whole switched off,
// which is how they are after reset. In that state `wfi` still wakes up for
// the interrupt, and the program carries on from the next instruction with
// no trap taken.
inline Program SleepUntilTheExternalInterruptThenStoreWord(
    std::uint64_t address) {
  Program program;
  program.push_back(Li(kT1, 1));
  program.push_back(Slli(kT1, kT1, kMachineExternalInterrupt));
  program.push_back(Csrs(kMie, kT1));
  program.push_back(kWfi);
  program.push_back(Lui(kT0, static_cast<Word>(address >> 12)));
  program.push_back(Sw(kZero, kT0, 0));
  AppendSleepForEver(program);
  return program;
}

// A program that counts down from `iterations` (a multiple of 4096) and
// then sleeps. Each time round the loop is two instructions, and all it
// asks of the bus is to fetch them.
inline Program CountDownThenSleep(Word iterations) {
  Program program;
  program.push_back(Lui(kT2, iterations >> 12));
  program.push_back(Addi(kT2, kT2, -1));
  program.push_back(Bne(kT2, kZero, -4));
  AppendSleepForEver(program);
  return program;
}

// A program that takes interrupts. It enables the one numbered
// `interrupt` (a bit of the mie register), switches interrupts on, and
// sleeps. Its handler quiets the device at `device` (an address as for
// StoreWordThenSleep) by writing to it, and returns to sleep.
inline Program HandleInterruptsByWritingTo(std::uint64_t device,
                                           Word interrupt) {
  Program program;
  // t2 = the address of the handler, worked out from where we are now.
  const std::size_t auipc_at = program.size();
  program.push_back(Auipc(kT2, 0));
  const std::size_t addi_at = program.size();
  program.push_back(0);  // filled in below, once the handler's place is known
  program.push_back(Csrw(kMtvec, kT2));
  program.push_back(Li(kT1, 1));
  program.push_back(Slli(kT1, kT1, interrupt));
  program.push_back(Csrs(kMie, kT1));
  program.push_back(Li(kT1, 1 << kInterruptsOn));
  program.push_back(Csrs(kMstatus, kT1));
  AppendSleepForEver(program);

  const std::size_t handler_at = program.size();
  program.push_back(Lui(kT0, static_cast<Word>(device >> 12)));
  program.push_back(Sw(kZero, kT0, 0));
  program.push_back(kMret);

  program[addi_at] =
      Addi(kT2, kT2, static_cast<std::int32_t>((handler_at - auipc_at) * 4));
  return program;
}

// A program that asks the machine timer for one interrupt and takes it.
// The timer's `mtimecmp` register is at `mtimecmp` and the interrupt is
// asked for when the timer has counted to `ticks` (below 2048). The handler
// puts the compare value out of reach again, writes a word to `probe` and
// goes back to sleep. Both addresses are as for StoreWordThenSleep.
inline Program TakeOneTimerInterrupt(std::uint64_t mtimecmp, std::int32_t ticks,
                                     std::uint64_t probe) {
  constexpr Word kT3 = 28;
  Program program;
  const std::size_t auipc_at = program.size();
  program.push_back(Auipc(kT2, 0));
  const std::size_t addi_at = program.size();
  program.push_back(0);  // filled in below, once the handler's place is known
  program.push_back(Csrw(kMtvec, kT2));
  program.push_back(Li(kT1, 1));
  program.push_back(Slli(kT1, kT1, kMachineTimerInterrupt));
  program.push_back(Csrs(kMie, kT1));
  program.push_back(Li(kT1, 1 << kInterruptsOn));
  program.push_back(Csrs(kMstatus, kT1));
  // The compare value is 64 bits, written as two words. Its high word is
  // all ones after reset, so the low word can go first.
  program.push_back(Lui(kT3, static_cast<Word>(mtimecmp >> 12)));
  program.push_back(Li(kT1, ticks));
  program.push_back(Sw(kT1, kT3, 0));
  program.push_back(Sw(kZero, kT3, 4));
  AppendSleepForEver(program);

  const std::size_t handler_at = program.size();
  program.push_back(Li(kT1, -1));
  program.push_back(Sw(kT1, kT3, 4));
  program.push_back(Lui(kT0, static_cast<Word>(probe >> 12)));
  program.push_back(Sw(kZero, kT0, 0));
  program.push_back(kMret);

  program[addi_at] =
      Addi(kT2, kT2, static_cast<std::int32_t>((handler_at - auipc_at) * 4));
  return program;
}

}  // namespace riscv

#endif  // TESTS_CPP_SUPPORT_RISCV_PROGRAM_H_
