#ifndef TESTS_CPP_SUPPORT_RISCV_PROGRAM_H_
#define TESTS_CPP_SUPPORT_RISCV_PROGRAM_H_

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
// Jump to pc + offset, leaving the return address in rd.
constexpr Word Jal(Word rd, std::int32_t offset) {
  const Word immediate = Field(offset, 21);
  return ((immediate >> 20) << 31) | (((immediate >> 1) & 0x3FF) << 21) |
         (((immediate >> 11) & 1) << 20) | (((immediate >> 12) & 0xFF) << 12) |
         (rd << 7) | 0x6F;
}
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
// 0x8000'0000) and then sleeps.
inline Program StoreWordThenSleep(std::uint64_t address) {
  Program program;
  program.push_back(Lui(kT0, static_cast<Word>(address >> 12)));
  program.push_back(Sw(kZero, kT0, 0));
  AppendSleepForEver(program);
  return program;
}

}  // namespace riscv

#endif  // TESTS_CPP_SUPPORT_RISCV_PROGRAM_H_
