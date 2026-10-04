#ifndef SPIKES_ISS_HARNESS_RV_ASM_H_
#define SPIKES_ISS_HARNESS_RV_ASM_H_

#include <cstdint>
#include <vector>

// Just enough of a RISC-V assembler to write the spike's bare-metal test
// programs by hand, so that they need no toolchain. Every instruction here
// is in the base integer set and encodes the same for 32 and 64 bits, so
// one program runs on both.
namespace spike::rv {

using Word = std::uint32_t;
using Program = std::vector<Word>;

// Registers, by their number.
inline constexpr Word kZero = 0;
inline constexpr Word kT0 = 5;
inline constexpr Word kT1 = 6;
inline constexpr Word kT2 = 7;
inline constexpr Word kT3 = 28;

// Control and status registers: where a trap jumps to, and where it came
// from.
inline constexpr Word kMtvec = 0x305;
inline constexpr Word kMepc = 0x341;

// A signed immediate, cut down to the low `bits` bits of its encoding.
constexpr Word Field(std::int32_t value, unsigned bits) {
  return static_cast<Word>(value) & ((Word{1} << bits) - 1);
}

constexpr Word Lui(Word rd, Word upper20) {
  return (upper20 << 12) | (rd << 7) | 0x37;
}
constexpr Word Auipc(Word rd, Word upper20) {
  return (upper20 << 12) | (rd << 7) | 0x17;
}
constexpr Word Addi(Word rd, Word rs1, std::int32_t immediate) {
  return (Field(immediate, 12) << 20) | (rs1 << 15) | (rd << 7) | 0x13;
}
constexpr Word Li(Word rd, std::int32_t immediate) {
  return Addi(rd, kZero, immediate);
}
// Store the low byte of rs2 at offset(rs1).
constexpr Word Sb(Word rs2, Word rs1, std::int32_t offset) {
  const Word immediate = Field(offset, 12);
  return ((immediate >> 5) << 25) | (rs2 << 20) | (rs1 << 15) |
         ((immediate & 0x1F) << 7) | 0x23;
}
// Branch to pc + offset if rs1 != rs2.
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
// Swap rs1 into a control and status register; its old value goes to rd.
constexpr Word Csrrw(Word rd, Word csr, Word rs1) {
  return (csr << 20) | (rs1 << 15) | (1 << 12) | (rd << 7) | 0x73;
}
// Read a control and status register into rd (setting no bits).
constexpr Word Csrr(Word rd, Word csr) {
  return (csr << 20) | (2 << 12) | (rd << 7) | 0x73;
}
inline constexpr Word kEcall = 0x0000'0073;
inline constexpr Word kMret = 0x3020'0073;
inline constexpr Word kWfi = 0x1050'0073;

// Sleep for ever: wait for an interrupt, and if one comes, wait again.
inline void AppendSleepForEver(Program& program) {
  program.push_back(kWfi);
  program.push_back(Jal(kZero, -4));
}

// Print one character: the UART's address is expected in t0.
inline void AppendPrint(Program& program, char character) {
  program.push_back(Li(kT1, character));
  program.push_back(Sb(kT1, kT0, 0));
}

// The smoke program. It prints "OK", takes a trap and comes back from it,
// and then sleeps. Run on a working CPU, the UART shows "OK\nTR\n": the T
// is printed by the trap handler and the R after returning from it.
inline Program SmokeProgram(std::uint64_t uart_base) {
  Program program;
  program.push_back(Lui(kT0, static_cast<Word>(uart_base >> 12)));
  // t2 = the address of the handler, worked out from where we are now.
  const std::size_t auipc_at = program.size();
  program.push_back(Auipc(kT2, 0));
  const std::size_t addi_at = program.size();
  program.push_back(0);  // filled in below, once the handler's place is known
  program.push_back(Csrrw(kZero, kMtvec, kT2));
  AppendPrint(program, 'O');
  AppendPrint(program, 'K');
  AppendPrint(program, '\n');
  program.push_back(kEcall);
  AppendPrint(program, 'R');
  AppendPrint(program, '\n');
  AppendSleepForEver(program);

  // The trap handler: print, step past the ecall, return.
  const std::size_t handler_at = program.size();
  AppendPrint(program, 'T');
  program.push_back(Csrr(kT3, kMepc));
  program.push_back(Addi(kT3, kT3, 4));
  program.push_back(Csrrw(kZero, kMepc, kT3));
  program.push_back(kMret);

  program[addi_at] =
      Addi(kT2, kT2, static_cast<std::int32_t>((handler_at - auipc_at) * 4));
  return program;
}

// A loop that counts down from `iterations` (a multiple of 4096) and then
// prints "D", for measuring speed. It executes two instructions per
// iteration.
inline Program CountdownProgram(std::uint64_t uart_base, Word iterations) {
  Program program;
  program.push_back(Lui(kT0, static_cast<Word>(uart_base >> 12)));
  program.push_back(Lui(kT2, iterations >> 12));
  program.push_back(Addi(kT2, kT2, -1));
  program.push_back(Bne(kT2, kZero, -4));
  AppendPrint(program, 'D');
  AppendSleepForEver(program);
  return program;
}

}  // namespace spike::rv

#endif  // SPIKES_ISS_HARNESS_RV_ASM_H_
