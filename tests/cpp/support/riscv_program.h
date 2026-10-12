#ifndef TESTS_CPP_SUPPORT_RISCV_PROGRAM_H_
#define TESTS_CPP_SUPPORT_RISCV_PROGRAM_H_

#include <cstddef>
#include <cstdint>
#include <initializer_list>
#include <vector>

// Just enough of a RISC-V assembler to write a CPU test's program by hand,
// so that the tests need no toolchain. Every instruction here is in the
// base integer set and is encoded the same for 32 and 64 bits, but for the
// few that say otherwise.
namespace riscv {

using Word = std::uint32_t;
using Program = std::vector<Word>;

// Registers, by their number.
inline constexpr Word kZero = 0;
// Where a call leaves the address to return to.
inline constexpr Word kRa = 1;
inline constexpr Word kT0 = 5;
inline constexpr Word kT1 = 6;
inline constexpr Word kT2 = 7;
inline constexpr Word kT3 = 28;
inline constexpr Word kT4 = 29;
inline constexpr Word kT5 = 30;
inline constexpr Word kT6 = 31;

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
// Store all 64 bits of rs2 at offset(rs1). Only a 64-bit core has it.
constexpr Word Sd(Word rs2, Word rs1, std::int32_t offset) {
  return Sb(rs2, rs1, offset) | (3 << 12);
}
// Load the 32-bit word at offset(rs1) into rd.
constexpr Word Lw(Word rd, Word rs1, std::int32_t offset) {
  return (Field(offset, 12) << 20) | (rs1 << 15) | (2 << 12) | (rd << 7) | 0x03;
}
// Load all 64 bits at offset(rs1) into rd. Only a 64-bit core has it.
constexpr Word Ld(Word rd, Word rs1, std::int32_t offset) {
  return (Field(offset, 12) << 20) | (rs1 << 15) | (3 << 12) | (rd << 7) | 0x03;
}
// Jump to rs1 + offset, leaving the return address in rd.
constexpr Word Jalr(Word rd, Word rs1, std::int32_t offset) {
  return (Field(offset, 12) << 20) | (rs1 << 15) | (rd << 7) | 0x67;
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
// rd = a control and status register.
constexpr Word Csrr(Word rd, Word csr) {
  return (csr << 20) | (2 << 12) | (rd << 7) | 0x73;
}
// rd = a control and status register, which is then written with rs1.
constexpr Word Csrrw(Word rd, Word csr, Word rs1) {
  return (csr << 20) | (rs1 << 15) | (1 << 12) | (rd << 7) | 0x73;
}
// Clear, in a control and status register, the bits that are set in rs1.
constexpr Word Csrc(Word csr, Word rs1) {
  return (csr << 20) | (rs1 << 15) | (3 << 12) | 0x73;
}
// Write rs1 to a control and status register.
constexpr Word Csrw(Word csr, Word rs1) {
  return (csr << 20) | (rs1 << 15) | (1 << 12) | 0x73;
}
// Floating-point register `rd` = the 64 bits of integer register rs1, as
// they are. Only a 64-bit core with double-precision floating point (the D
// extension) has it.
constexpr Word FmvDX(Word rd, Word rs1) {
  return 0xF200'0053 | (rs1 << 15) | (rd << 7);
}
// Integer register `rd` = the 64 bits of floating-point register rs1, as
// they are. For the same cores as FmvDX.
constexpr Word FmvXD(Word rd, Word rs1) {
  return 0xE200'0053 | (rs1 << 15) | (rd << 7);
}
// The control and status register that says which interrupts are enabled,
// and its bits for the machine timer and machine external interrupts.
inline constexpr Word kMie = 0x304;
inline constexpr Word kMachineTimerInterrupt = 7;
inline constexpr Word kMachineExternalInterrupt = 11;
// The register that says which interrupts are pending, a bit each as in
// `mie`.
inline constexpr Word kMip = 0x344;
// The status register, and its bit that switches interrupts on as a whole.
inline constexpr Word kMstatus = 0x300;
inline constexpr Word kInterruptsOn = 3;
// The low bit of its two-bit field that says what state the floating-point
// registers are in. While the field is zero, as after reset, they are
// switched off and a floating-point instruction is an illegal one.
inline constexpr Word kFloatingPointOn = 13;
// Its two-bit field that says which mode `mret` returns to, by the place
// of its low bit: 1 there is supervisor mode, and 3 is machine mode.
inline constexpr Word kPreviousMode = 11;
// Its bit that switches interrupts on for supervisor mode.
inline constexpr Word kSupervisorInterruptsOn = 1;
// The register a hart reads the machine timer's count from, read-only.
inline constexpr Word kTime = 0xC01;
// The upper half of the count, which a 32-bit hart has in a register of
// its own.
inline constexpr Word kTimeh = 0xC81;
// The register that holds the address a trap jumps to, and the one that
// says why the trap was taken: 2 for an illegal instruction.
inline constexpr Word kMtvec = 0x305;
inline constexpr Word kMcause = 0x342;
inline constexpr Word kIllegalInstruction = 2;
// A hart's way to the registers of its IMSIC's interrupt file for machine
// mode: firmware writes the number of one to `miselect` and then finds it
// at `mireg`. And the register a handler claims through: a read is the
// identity to see to, in bits 26 to 16, and a write takes it.
inline constexpr Word kMiselect = 0x350;
inline constexpr Word kMireg = 0x351;
inline constexpr Word kMtopei = 0x35C;
// The same three for the file that is supervisor mode's.
inline constexpr Word kSiselect = 0x150;
inline constexpr Word kSireg = 0x151;
inline constexpr Word kStopei = 0x15C;
// Two of a file's registers, by the numbers they are selected with:
// whether the file may interrupt at all, and which identities firmware
// wants to hear of, a bit each.
inline constexpr Word kEidelivery = 0x70;
inline constexpr Word kEie0 = 0xC0;
// The register that holds the address `mret` returns to.
inline constexpr Word kMepc = 0x341;
// The register that says which interrupts are handed down to supervisor
// mode, and the bit, there and among the enables, of the supervisor
// external interrupt.
inline constexpr Word kMideleg = 0x303;
inline constexpr Word kSupervisorExternalInterrupt = 9;
// The bit of the supervisor software interrupt, which software asks for.
inline constexpr Word kSupervisorSoftwareInterrupt = 1;
// Supervisor mode's own view of the interrupt enables, and the register
// that holds the address a trap taken in supervisor mode jumps to.
inline constexpr Word kSie = 0x104;
inline constexpr Word kStvec = 0x105;
// And its view of which interrupts are pending.
inline constexpr Word kSip = 0x144;
// Supervisor mode's view of the status register, and two of its bits, by
// their place in the upper twenty that `lui` sets: SUM lets supervisor
// mode use user mode's pages, and MXR lets a load read a page that may
// otherwise only be executed.
inline constexpr Word kSstatus = 0x100;
inline constexpr Word kSupervisorUserMemoryInUpper20 = 1 << (18 - 12);
inline constexpr Word kMakeExecutableReadableInUpper20 = 1 << (19 - 12);
// The register that says which exceptions are handed down to supervisor
// mode, a bit for each cause, and the three causes that are page faults:
// of an instruction fetch, of a load and of a store.
inline constexpr Word kMedeleg = 0x302;
inline constexpr Word kInstructionPageFault = 12;
inline constexpr Word kLoadPageFault = 13;
inline constexpr Word kStorePageFault = 15;
// Supervisor mode's own why and where of a trap: the cause, and for a
// fault the address that could not be used.
inline constexpr Word kScause = 0x142;
inline constexpr Word kStval = 0x143;
// The register that turns paging on: which kind of page table, in its top
// four bits, and the number of the page the first table is in. 8 is Sv39,
// tables of three levels that translate an address of 39 bits, and 9 and
// 10 are Sv48 and Sv57, of four levels and five.
inline constexpr Word kSatp = 0x180;
constexpr std::uint64_t Satp(std::uint64_t kind, std::uint64_t root_table) {
  return (kind << 60) | (root_table >> 12);
}
constexpr std::uint64_t SatpForSv39(std::uint64_t root_table) {
  return Satp(8, root_table);
}
// Its sixteen bits between those two, for an address-space identifier.
inline constexpr std::uint64_t kSatpIdentifier = std::uint64_t{0xFFFF} << 44;
// An entry of a page table: the number of the page it leads to, ten bits
// up, over bits that say what the entry is. Valid alone is a pointer to
// the next table down. With any of read, write and execute it is a page,
// and those say what may be done there. Accessed and dirty say whether
// the page has been used at all and whether it has been written.
inline constexpr std::uint64_t kPteValid = 0x01;
inline constexpr std::uint64_t kPteRead = 0x02;
inline constexpr std::uint64_t kPteWrite = 0x04;
inline constexpr std::uint64_t kPteExecute = 0x08;
// A page of user mode's, which supervisor mode may not use unless it says
// it means to.
inline constexpr std::uint64_t kPteUser = 0x10;
inline constexpr std::uint64_t kPteAccessed = 0x40;
inline constexpr std::uint64_t kPteDirty = 0x80;
constexpr std::uint64_t PageTableEntry(std::uint64_t leads_to,
                                       std::uint64_t bits) {
  return ((leads_to >> 12) << 10) | bits;
}
// Return from a call, in the two bytes a compressed instruction takes.
inline constexpr std::uint16_t kCompressedRet = 0x8082;
// Return from a trap handler to where the trap was taken.
inline constexpr Word kMret = 0x3020'0073;
// The same, from a handler in supervisor mode.
inline constexpr Word kSret = 0x1020'0073;
// Wait for an interrupt.
inline constexpr Word kWfi = 0x1050'0073;

// How far past its first instruction a program leaves its result.
inline constexpr std::int32_t kResultOffset = 0x200;

// Sleep for ever: wait for an interrupt, and if one comes, wait again.
inline void AppendSleepForEver(Program& program) {
  program.push_back(kWfi);
  program.push_back(Jal(kZero, -4));
}

// A program put together an instruction at a time, which can have 64-bit
// constants in it.
//
// 🎓 `lui` and `addi` make a constant of 32 bits, with its sign carried up
// into the rest of a 64-bit register, which is no way to an address in the
// upper half of memory or to a page-table entry. What a compiler does
// instead is keep such constants as data after the code, in a **literal
// pool**, and load one by its distance from the instruction that wants it.
// That works wherever the program runs, which matters here: a program that
// turns paging on runs at two addresses, the one it was loaded at and the
// one its pages say.
class Assembler {
 public:
  // Which constant of the pool, for Set.
  using Constant = std::size_t;

  void Emit(Word instruction) { code_.push_back(instruction); }
  void Emit(std::initializer_list<Word> instructions) {
    code_.insert(code_.end(), instructions);
  }

  // How far the next instruction is from the first, in bytes.
  std::uint64_t Here() const { return code_.size() * 4; }

  // rd = `value`, loaded from the pool. A value that is not known yet, the
  // address of code further down, is given later with Set.
  Constant Load(Word rd, std::uint64_t value = 0) {
    loads_.push_back({.at = code_.size(), .rd = rd, .of = pool_.size()});
    // rd = the address of this instruction, then what is `offset` past it,
    // which Assemble fills in when it knows where the pool starts.
    code_.push_back(Auipc(rd, 0));
    code_.push_back(0);
    pool_.push_back(value);
    return pool_.size() - 1;
  }
  void Set(Constant constant, std::uint64_t value) { pool_[constant] = value; }

  // The program: the code, and then the pool, on a boundary of eight bytes
  // from the first instruction, since a load of eight bytes from anywhere
  // else traps. So the program has to be loaded at such a boundary too.
  Program Assemble() const {
    Program program = code_;
    if (program.size() % 2 != 0) program.push_back(0);
    const std::size_t pool_at = program.size();
    for (const Loaded& load : loads_) {
      const std::size_t words_ahead = pool_at + (2 * load.of) - load.at;
      program[load.at + 1] =
          Ld(load.rd, load.rd, static_cast<std::int32_t>(words_ahead * 4));
    }
    for (const std::uint64_t value : pool_) {
      program.push_back(static_cast<Word>(value));
      program.push_back(static_cast<Word>(value >> 32));
    }
    return program;
  }

 private:
  struct Loaded {
    // Which word of the code the load starts at.
    std::size_t at;
    Word rd;
    Constant of;
  };

  Program code_;
  std::vector<Loaded> loads_;
  std::vector<std::uint64_t> pool_;
};

inline void AppendSleepForEver(Assembler& program) {
  program.Emit({kWfi, Jal(kZero, -4)});
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

// A program that counts how many times it has been started, in its result
// word, and then spins or sleeps for ever. It only ever stops by being
// reset, and what was in memory before a reset is still there after it, so
// the count is the number of times the CPU came out of reset.
//
// The first time, it first writes a one to the word at `ask_at` if that is
// not zero (`ask_at` is as `address` is for StoreWordThenSleep): a program
// that asks for its own reset.
inline Program CountStartsThen(bool sleep, std::uint64_t ask_at = 0) {
  Program program;
  program.push_back(Auipc(kT0, 0));
  program.push_back(Lw(kT1, kT0, kResultOffset));
  program.push_back(Addi(kT1, kT1, 1));
  program.push_back(Sw(kT1, kT0, kResultOffset));
  if (ask_at != 0) {
    const auto page = static_cast<Word>(ask_at >> 12);
    const auto within = static_cast<std::int32_t>(ask_at & 0xFFF);
    program.push_back(Li(kT2, 1));
    // Past the three instructions that ask, to where the waiting starts.
    program.push_back(Bne(kT1, kT2, 4 * 4));
    program.push_back(Lui(kT0, page));
    program.push_back(Li(kT1, 1));
    program.push_back(Sw(kT1, kT0, within));
  }
  if (sleep) {
    AppendSleepForEver(program);
  } else {
    program.push_back(Jal(kZero, 0));
  }
  return program;
}

// A program that switches floating point on, moves `value` into a
// floating-point register and back out, stores what came out as its result
// and sleeps. On a core with no floating point the move is an illegal
// instruction, and nothing is stored.
inline Program MoveByteThroughAFloatingPointRegisterThenSleep(
    std::uint8_t value) {
  constexpr Word kFt0 = 0;
  Program program;
  program.push_back(Auipc(kT0, 0));
  program.push_back(Li(kT1, 1));
  program.push_back(Slli(kT1, kT1, kFloatingPointOn));
  program.push_back(Csrs(kMstatus, kT1));
  program.push_back(Li(kT1, value));
  program.push_back(FmvDX(kFt0, kT1));
  program.push_back(FmvXD(kT2, kFt0));
  program.push_back(Sb(kT2, kT0, kResultOffset));
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

// A program that sleeps until the line of `interrupt` is high, clears that
// interrupt's bit in `mip`, sleeps again, and stores a one as its result
// when it wakes.
//
// Zephyr clears the bit the same way, on its way into every handler. This
// program leaves interrupts as a whole switched off, as
// SleepUntilTheExternalInterruptThenStoreWord does, so no trap is taken and
// nothing quiets whatever holds the line high.
inline Program SleepClearTheInterruptInMipAndSleepAgainThenStoreOne(
    Word interrupt) {
  Program program;
  program.push_back(Auipc(kT0, 0));
  program.push_back(Li(kT1, 1));
  program.push_back(Slli(kT1, kT1, interrupt));
  program.push_back(Csrs(kMie, kT1));
  program.push_back(kWfi);
  program.push_back(Csrc(kMip, kT1));
  program.push_back(kWfi);
  program.push_back(Li(kT1, 1));
  program.push_back(Sw(kT1, kT0, kResultOffset));
  AppendSleepForEver(program);
  return program;
}

// A program that has the external interrupt arrive at a load, and stores
// what the load got as its result.
//
// It enables the interrupt, sleeps with interrupts as a whole switched off
// until the line is high, and then switches them on. So the interrupt
// arrives at the very next instruction, which loads the program's own
// first word: the load runs to its end, and then the trap is taken. Its
// handler quiets the device at `device` (an address as for
// StoreWordThenSleep) by writing to it, and returns to the store after the
// load.
inline Program TakeTheExternalInterruptAtALoadOfItsOwnFirstWord(
    std::uint64_t device) {
  Program program;
  program.push_back(Auipc(kT3, 0));
  // t2 = the address of the handler, worked out from where we are now.
  const std::size_t auipc_at = program.size();
  program.push_back(Auipc(kT2, 0));
  const std::size_t addi_at = program.size();
  program.push_back(0);  // filled in below, once the handler's place is known
  program.push_back(Csrw(kMtvec, kT2));
  program.push_back(Li(kT1, 1));
  program.push_back(Slli(kT1, kT1, kMachineExternalInterrupt));
  program.push_back(Csrs(kMie, kT1));
  program.push_back(kWfi);
  program.push_back(Li(kT1, 1 << kInterruptsOn));
  // What the load would leave untouched, if it did not happen.
  program.push_back(Li(kT0, 0));
  program.push_back(Csrs(kMstatus, kT1));
  program.push_back(Lw(kT0, kT3, 0));
  program.push_back(Sw(kT0, kT3, kResultOffset));
  AppendSleepForEver(program);

  const std::size_t handler_at = program.size();
  program.push_back(Lui(kT1, static_cast<Word>(device >> 12)));
  program.push_back(Sw(kZero, kT1, 0));
  program.push_back(kMret);

  program[addi_at] =
      Addi(kT2, kT2, static_cast<std::int32_t>((handler_at - auipc_at) * 4));
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

// A program that counts down from `iterations` (as for
// CountDownThenSleep), then reads the `time` register and, with its very
// next instruction, the low word of the machine timer's count where the
// timer has it on the bus, at `mtime` (an address below 0x8000'0000). It
// stores the two as its result, `time` first and the timer's own a word
// after, and sleeps.
inline Program ReadTimeThenTheTimersOwnCountThenSleep(std::uint64_t mtime,
                                                      Word iterations) {
  // The address in two parts: what Lui can load, and what is left for the
  // load's offset, which is signed and of 12 bits.
  const Word upper = static_cast<Word>((mtime + 0x800) >> 12);
  const auto lower =
      static_cast<std::int32_t>(mtime - (std::uint64_t{upper} << 12));
  Program program;
  program.push_back(Auipc(kT0, 0));
  program.push_back(Lui(kT3, upper));
  program.push_back(Lui(kT2, iterations >> 12));
  program.push_back(Addi(kT2, kT2, -1));
  program.push_back(Bne(kT2, kZero, -4));
  program.push_back(Csrr(kT1, kTime));
  program.push_back(Lw(kT4, kT3, lower));
  program.push_back(Sw(kT1, kT0, kResultOffset));
  program.push_back(Sw(kT4, kT0, kResultOffset + 4));
  AppendSleepForEver(program);
  return program;
}

// A program that counts down from `iterations` (as for
// CountDownThenSleep), reads the low word of the machine timer's count at
// `mtime` (as for ReadTimeThenTheTimersOwnCountThenSleep), sets the timer's
// compare value at `mtimecmp` (a multiple of 4096 below 0x8000'0000), and
// reads the count again. It stores the two counts as its result, the
// earlier one first, and sleeps.
//
// It sets the compare value the way Zephyr does on a hart of `xlen` bits.
// One of 64 writes it whole. One of 32 writes it in three: the high word
// to all ones, so that no value in between can interrupt, then the low
// word, then the high word. The value is all ones, a time too far off to
// come.
inline Program ReadTheTimersCountEitherSideOfSettingItsCompareValueThenSleep(
    std::uint64_t mtime, std::uint64_t mtimecmp, Word iterations, int xlen) {
  const Word upper = static_cast<Word>((mtime + 0x800) >> 12);
  const auto lower =
      static_cast<std::int32_t>(mtime - (std::uint64_t{upper} << 12));
  Program program;
  program.push_back(Auipc(kT0, 0));
  program.push_back(Lui(kT3, upper));
  program.push_back(Lui(kT6, static_cast<Word>(mtimecmp >> 12)));
  program.push_back(Li(kT1, -1));
  program.push_back(Lui(kT2, iterations >> 12));
  program.push_back(Addi(kT2, kT2, -1));
  program.push_back(Bne(kT2, kZero, -4));
  program.push_back(Lw(kT4, kT3, lower));
  if (xlen == 64) {
    program.push_back(Sd(kT1, kT6, 0));
  } else {
    program.push_back(Sw(kT1, kT6, 4));
    program.push_back(Sw(kT1, kT6, 0));
    program.push_back(Sw(kT1, kT6, 4));
  }
  program.push_back(Lw(kT5, kT3, lower));
  program.push_back(Sw(kT4, kT0, kResultOffset));
  program.push_back(Sw(kT5, kT0, kResultOffset + 4));
  AppendSleepForEver(program);
  return program;
}

// A program for a 32-bit core that writes `value` to the upper half of
// the machine timer's count, where the timer has the count on the bus, at
// `mtime` (as for ReadTimeThenTheTimersOwnCountThenSleep), then reads its
// `timeh` register, stores what it read as its result, and sleeps.
inline Program WriteTheUpperHalfOfTheTimersCountThenStoreTimeh(
    std::uint64_t mtime, std::int32_t value) {
  const Word upper = static_cast<Word>((mtime + 0x800) >> 12);
  const auto lower =
      static_cast<std::int32_t>(mtime - (std::uint64_t{upper} << 12));
  Program program;
  program.push_back(Auipc(kT0, 0));
  program.push_back(Lui(kT3, upper));
  program.push_back(Li(kT1, value));
  program.push_back(Sw(kT1, kT3, lower + 4));
  program.push_back(Csrr(kT1, kTimeh));
  program.push_back(Sw(kT1, kT0, kResultOffset));
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

// A program that runs `body` in supervisor mode with `handler` as that
// mode's trap handler, as an operating system under a machine-mode monitor
// runs. In machine mode it hands the interrupt numbered `interrupt` down to
// supervisor mode, enables it, and drops to supervisor mode with interrupts
// on. Both parts find the program's own first address in t3, which is
// kResultOffset short of where a result goes.
inline Program InSupervisorMode(Word interrupt, const Program& body,
                                const Program& handler) {
  Program program;
  program.push_back(Auipc(kT3, 0));
  // t2 = the address of the handler, worked out from where we are now.
  const std::size_t handler_auipc_at = program.size();
  program.push_back(Auipc(kT2, 0));
  const std::size_t handler_addi_at = program.size();
  program.push_back(0);  // filled in below
  program.push_back(Csrw(kStvec, kT2));
  program.push_back(Li(kT1, 1));
  program.push_back(Slli(kT1, kT1, interrupt));
  program.push_back(Csrs(kMideleg, kT1));
  program.push_back(Csrs(kSie, kT1));
  program.push_back(Li(kT1, 1 << kSupervisorInterruptsOn));
  program.push_back(Csrs(kMstatus, kT1));
  // The mode to return to is supervisor: clear both bits of the field,
  // then set it to 1.
  program.push_back(Li(kT1, 3));
  program.push_back(Slli(kT1, kT1, kPreviousMode));
  program.push_back(Csrc(kMstatus, kT1));
  program.push_back(Li(kT1, 1));
  program.push_back(Slli(kT1, kT1, kPreviousMode));
  program.push_back(Csrs(kMstatus, kT1));
  // And where: the body below.
  const std::size_t body_auipc_at = program.size();
  program.push_back(Auipc(kT2, 0));
  const std::size_t body_addi_at = program.size();
  program.push_back(0);  // filled in below
  program.push_back(Csrw(kMepc, kT2));
  program.push_back(kMret);

  const std::size_t body_at = program.size();
  program.insert(program.end(), body.begin(), body.end());
  const std::size_t handler_at = program.size();
  program.insert(program.end(), handler.begin(), handler.end());

  program[handler_addi_at] = Addi(
      kT2, kT2, static_cast<std::int32_t>((handler_at - handler_auipc_at) * 4));
  program[body_addi_at] =
      Addi(kT2, kT2, static_cast<std::int32_t>((body_at - body_auipc_at) * 4));
  return program;
}

// A program that takes interrupts that arrive as messages at an IMSIC, the
// way an operating system does. Through its hart's registers it switches
// the IMSIC's delivery on and has it listen for `identity` (below 64),
// enables the external interrupt and sleeps. Its handler claims the
// interrupt, which is all that quiets an IMSIC, and returns. It touches no
// memory, so that nothing but the claim gives the rest of the platform a
// turn before it returns. Each time it is woken, the program stores two
// words as its result: the identity the handler last claimed, and a word
// after it how many times the handler has run.
inline Program HandleMessagesThroughAnImsic(Word identity) {
  Program program;
  // t3 = where the result goes, and t4 = how many times the handler ran.
  program.push_back(Auipc(kT3, 0));
  program.push_back(Li(kT4, 0));
  const std::size_t auipc_at = program.size();
  program.push_back(Auipc(kT2, 0));
  const std::size_t addi_at = program.size();
  program.push_back(0);  // filled in below, once the handler's place is known
  program.push_back(Csrw(kMtvec, kT2));
  program.push_back(Li(kT1, kEidelivery));
  program.push_back(Csrw(kMiselect, kT1));
  program.push_back(Li(kT1, 1));
  program.push_back(Csrw(kMireg, kT1));
  program.push_back(Li(kT1, kEie0));
  program.push_back(Csrw(kMiselect, kT1));
  program.push_back(Li(kT1, 1));
  program.push_back(Slli(kT1, kT1, identity));
  program.push_back(Csrs(kMireg, kT1));
  program.push_back(Li(kT1, 1));
  program.push_back(Slli(kT1, kT1, kMachineExternalInterrupt));
  program.push_back(Csrs(kMie, kT1));
  program.push_back(Li(kT0, 0));
  program.push_back(Li(kT1, 1 << kInterruptsOn));
  program.push_back(Csrs(kMstatus, kT1));
  // Sleep, and each time something wakes the hart, store what the handler
  // left in t0 and t4. An interrupt is taken after the instruction it
  // arrives at, which is the one after the sleep, so that one does nothing.
  program.push_back(kWfi);
  program.push_back(Addi(kZero, kZero, 0));
  program.push_back(Sw(kT0, kT3, kResultOffset));
  program.push_back(Sw(kT4, kT3, kResultOffset + 4));
  program.push_back(Jal(kZero, -16));

  const std::size_t handler_at = program.size();
  program.push_back(Csrrw(kT0, kMtopei, kZero));
  program.push_back(Srli(kT0, kT0, 16));
  program.push_back(Addi(kT4, kT4, 1));
  program.push_back(kMret);

  program[addi_at] =
      Addi(kT2, kT2, static_cast<std::int32_t>((handler_at - auipc_at) * 4));
  return program;
}

// The same for an operating system in supervisor mode, with the IMSIC's
// file for that mode: it is switched on, listened to and claimed from
// through supervisor mode's three registers, and the interrupt is the
// supervisor external one, handed down to that mode and taken there.
inline Program HandleMessagesInSupervisorModeThroughAnImsic(Word identity) {
  Program listen_then_sleep{
      Li(kT1, kEidelivery),
      Csrw(kSiselect, kT1),
      Li(kT1, 1),
      Csrw(kSireg, kT1),
      Li(kT1, kEie0),
      Csrw(kSiselect, kT1),
      Li(kT1, 1),
      Slli(kT1, kT1, identity),
      Csrs(kSireg, kT1),
      // t0 = what the handler last claimed, and t4 = how many times it ran.
      Li(kT0, 0),
      Li(kT4, 0),
      // As HandleMessagesThroughAnImsic sleeps and stores.
      kWfi,
      Addi(kZero, kZero, 0),
      Sw(kT0, kT3, kResultOffset),
      Sw(kT4, kT3, kResultOffset + 4),
      Jal(kZero, -16),
  };
  return InSupervisorMode(kSupervisorExternalInterrupt, listen_then_sleep,
                          {Csrrw(kT0, kStopei, kZero), Srli(kT0, kT0, 16),
                           Addi(kT4, kT4, 1), kSret});
}

// A program that, in machine mode, writes `for_machine_mode` to `miselect`
// and then `for_supervisor_mode` to `siselect` (each below 2048), and
// stores what the two then read as its result: `miselect`, and a word
// after it `siselect`. Then it sleeps.
inline Program SelectForMachineModeThenForSupervisorModeAndStoreBoth(
    Word for_machine_mode, Word for_supervisor_mode) {
  Program program{
      Auipc(kT3, 0),
      Li(kT1, static_cast<std::int32_t>(for_machine_mode)),
      Csrw(kMiselect, kT1),
      Li(kT1, static_cast<std::int32_t>(for_supervisor_mode)),
      Csrw(kSiselect, kT1),
      Csrr(kT1, kMiselect),
      Sw(kT1, kT3, kResultOffset),
      Csrr(kT1, kSiselect),
      Sw(kT1, kT3, kResultOffset + 4),
  };
  AppendSleepForEver(program);
  return program;
}

// Where things are for a program that runs under paging, which it cannot
// work out from its own address as the others do: it runs at two.
struct Pages {
  // The physical address of the first page table.
  std::uint64_t root_table;
  // The virtual address the page the program is loaded in is mapped at.
  std::uint64_t code;
  // The virtual address of a page the program may write. Its result goes
  // there, in words of 64 bits.
  std::uint64_t result;
};

// Machine mode's part of a program that runs under paging: it turns Sv39
// on, with the tables `at` says, and drops to supervisor mode at whatever
// instruction comes after this, by that instruction's virtual address.
// 💡 No monitor does this: it hands over with paging off, and an operating
// system turns it on for itself. Machine mode's own addresses are never
// translated, so doing it here lets a program arrive at its virtual
// address with nothing mapped where it was loaded.
inline void AppendEnterSupervisorModeUnderPaging(Assembler& program,
                                                 const Pages& at) {
  program.Load(kT1, SatpForSv39(at.root_table));
  program.Emit({Csrw(kSatp, kT1),
                // The mode to return to is supervisor, as InSupervisorMode
                // sets it.
                Li(kT1, 3), Slli(kT1, kT1, kPreviousMode), Csrc(kMstatus, kT1),
                Li(kT1, 1), Slli(kT1, kT1, kPreviousMode),
                Csrs(kMstatus, kT1)});
  const Assembler::Constant entry = program.Load(kT1);
  program.Emit({Csrw(kMepc, kT1), kMret});
  program.Set(entry, at.code + program.Here());
}

// A program that runs under paging in supervisor mode, at its virtual
// address, and stores the address of one of its own instructions as its
// result. Then it sleeps.
inline Program StoreWhereItRunsInSupervisorModeUnderPaging(const Pages& at) {
  Assembler program;
  AppendEnterSupervisorModeUnderPaging(program, at);
  program.Emit(Auipc(kT1, 0));
  program.Load(kT2, at.result);
  program.Emit(Sd(kT1, kT2, 0));
  AppendSleepForEver(program);
  return program.Assemble();
}

// A program that, in supervisor mode under paging, with page faults handed
// down to that mode, puts `address` in t1 and executes `accesses`,
// instructions that use it and may use t0 as well. Its result is three
// words. Its trap handler stores two: why the trap was taken, the cause
// with one added so that zero is no trap at all, and the address the trap
// says. The third is one if every instruction was executed and none
// trapped. Either way it then sleeps.
inline Program StoreWhyAndWhereAccessesTrap(const Pages& at,
                                            std::uint64_t address,
                                            const Program& accesses) {
  Assembler program;
  program.Load(kT1, (std::uint64_t{1} << kInstructionPageFault) |
                        (std::uint64_t{1} << kLoadPageFault) |
                        (std::uint64_t{1} << kStorePageFault));
  program.Emit(Csrw(kMedeleg, kT1));
  AppendEnterSupervisorModeUnderPaging(program, at);
  const Assembler::Constant handler = program.Load(kT1);
  program.Emit(Csrw(kStvec, kT1));
  program.Load(kT1, address);
  for (const Word access : accesses) program.Emit(access);
  program.Load(kT2, at.result);
  program.Emit({Li(kT0, 1), Sd(kT0, kT2, 16)});
  AppendSleepForEver(program);

  program.Set(handler, at.code + program.Here());
  program.Emit({Csrr(kT1, kScause), Addi(kT1, kT1, 1)});
  program.Load(kT2, at.result);
  program.Emit({Sd(kT1, kT2, 0), Csrr(kT1, kStval), Sd(kT1, kT2, 8)});
  AppendSleepForEver(program);
  return program.Assemble();
}

// A program that, in machine mode, where `satp` translates nothing,
// stores what `satp` reads as before anything has written it, and then
// writes each of `values` to it in turn and stores what it reads as after
// each. Its result is those words, at `result`. Then it sleeps.
inline Program StoreWhatSatpReadsAsBeforeAndAfterWriting(
    std::initializer_list<std::uint64_t> values, std::uint64_t result) {
  Assembler program;
  program.Load(kT2, result);
  program.Emit({Csrr(kT1, kSatp), Sd(kT1, kT2, 0)});
  std::int32_t next = 8;
  for (const std::uint64_t value : values) {
    program.Load(kT1, value);
    program.Emit({Csrw(kSatp, kT1), Csrr(kT1, kSatp), Sd(kT1, kT2, next)});
    next += 8;
  }
  AppendSleepForEver(program);
  return program.Assemble();
}

// A program that, in supervisor mode under paging, counts down from
// `iterations` (above zero) to one, storing the count as its result each
// time round: three instructions, one of them a store. Then it sleeps.
inline Program CountDownUnderPagingStoringEachCount(const Pages& at,
                                                    std::uint64_t iterations) {
  Assembler program;
  AppendEnterSupervisorModeUnderPaging(program, at);
  program.Load(kT2, at.result);
  program.Load(kT1, iterations);
  program.Emit({Sd(kT1, kT2, 0), Addi(kT1, kT1, -1), Bne(kT1, kZero, -8)});
  AppendSleepForEver(program);
  return program.Assemble();
}

// A program that turns paging on for itself, as an operating system does.
// Machine mode drops to supervisor mode where the program is, with paging
// off. There it writes `satp`, runs on at the same addresses, which its
// tables have to map onto themselves for that, and jumps to its virtual
// address. It stores the address of an instruction there as its result,
// and sleeps.
inline Program TurnPagingOnInSupervisorModeThenStoreWhereItRuns(
    const Pages& at) {
  Assembler program;
  program.Emit({Li(kT1, 3), Slli(kT1, kT1, kPreviousMode), Csrc(kMstatus, kT1),
                Li(kT1, 1), Slli(kT1, kT1, kPreviousMode), Csrs(kMstatus, kT1),
                // To the instruction after the return, four on from here.
                Auipc(kT1, 0), Addi(kT1, kT1, 16), Csrw(kMepc, kT1), kMret});
  program.Load(kT1, SatpForSv39(at.root_table));
  program.Emit(Csrw(kSatp, kT1));
  const Assembler::Constant up_there = program.Load(kT1);
  program.Emit(Jalr(kZero, kT1, 0));
  program.Set(up_there, at.code + program.Here());
  program.Emit(Auipc(kT1, 0));
  program.Load(kT2, at.result);
  program.Emit(Sd(kT1, kT2, 0));
  AppendSleepForEver(program);
  return program.Assemble();
}

// A program that, in supervisor mode under paging, calls the code at the
// virtual address `code`, which a test has put there, and stores what that
// left in t0 as its result. Then it sleeps.
inline Program StoreWhatTheCodeAtAnAddressLeavesInT0(const Pages& at,
                                                     std::uint64_t code) {
  Assembler program;
  AppendEnterSupervisorModeUnderPaging(program, at);
  program.Emit(Li(kT0, 0));
  program.Load(kT1, code);
  program.Emit(Jalr(kRa, kT1, 0));
  program.Load(kT2, at.result);
  program.Emit(Sd(kT0, kT2, 0));
  AppendSleepForEver(program);
  return program.Assemble();
}

// A program that writes to the control and status register numbered `csr`
// and stores, as its result, why it trapped if it did: the trap's cause
// with one added, so that a result of zero is no trap at all. Then it
// sleeps.
inline Program StoreWhyWritingACsrTrapped(Word csr) {
  Program program;
  program.push_back(Auipc(kT3, 0));
  const std::size_t auipc_at = program.size();
  program.push_back(Auipc(kT2, 0));
  const std::size_t addi_at = program.size();
  program.push_back(0);  // filled in below, once the handler's place is known
  program.push_back(Csrw(kMtvec, kT2));
  program.push_back(Csrw(csr, kZero));
  AppendSleepForEver(program);

  const std::size_t handler_at = program.size();
  program.push_back(Csrr(kT1, kMcause));
  program.push_back(Addi(kT1, kT1, 1));
  program.push_back(Sw(kT1, kT3, kResultOffset));
  AppendSleepForEver(program);

  program[addi_at] =
      Addi(kT2, kT2, static_cast<std::int32_t>((handler_at - auipc_at) * 4));
  return program;
}

// A program that takes the supervisor external interrupt in supervisor
// mode, where it sleeps. Its handler, which a trap reaches only if it is
// taken in supervisor mode, quiets the device at `device` (an address as
// for StoreWordThenSleep) by writing to it, and returns to sleep.
inline Program HandleTheSupervisorExternalInterruptByWritingTo(
    std::uint64_t device) {
  Program sleep;
  AppendSleepForEver(sleep);
  return InSupervisorMode(
      kSupervisorExternalInterrupt, sleep,
      {Lui(kT0, static_cast<Word>(device >> 12)), Sw(kZero, kT0, 0), kSret});
}

// The same, whose handler first stores what supervisor mode sees of the
// interrupt as the program's result: its enables (`sie`), and a word after
// them what is pending (`sip`).
inline Program StoreSieThenSipOnTheSupervisorExternalInterrupt(
    std::uint64_t device) {
  Program sleep;
  AppendSleepForEver(sleep);
  return InSupervisorMode(
      kSupervisorExternalInterrupt, sleep,
      {Csrr(kT1, kSie), Sw(kT1, kT3, kResultOffset), Csrr(kT1, kSip),
       Sw(kT1, kT3, kResultOffset + 4),
       Lui(kT0, static_cast<Word>(device >> 12)), Sw(kZero, kT0, 0), kSret});
}

// A program that, with only the supervisor external interrupt handed down
// to it, tries in supervisor mode to enable all three of the supervisor's
// interrupts: software, timer and external, which are bits 1, 5 and 9. It
// stores what `sie` then reads as its result, and sleeps.
inline Program EnableEverySupervisorInterruptThenStoreSie() {
  Program body{
      Li(kT1, 0x222),
      Csrs(kSie, kT1),
      Csrr(kT1, kSie),
      Sw(kT1, kT3, kResultOffset),
  };
  AppendSleepForEver(body);
  return InSupervisorMode(kSupervisorExternalInterrupt, body, {kSret});
}

// A program that, in supervisor mode, asks for the supervisor software
// interrupt itself, by setting it pending in `sip`, and sleeps. Its handler
// takes the request back, adds one to the program's result, which is a
// count of the times it has run, and returns to sleep.
inline Program TakeASupervisorSoftwareInterruptOfItsOwnAsking() {
  Program ask_then_sleep{
      Li(kT1, 1 << kSupervisorSoftwareInterrupt),
      Csrs(kSip, kT1),
  };
  AppendSleepForEver(ask_then_sleep);
  return InSupervisorMode(
      kSupervisorSoftwareInterrupt, ask_then_sleep,
      {Li(kT1, 1 << kSupervisorSoftwareInterrupt), Csrc(kSip, kT1),
       Lw(kT4, kT3, kResultOffset), Addi(kT4, kT4, 1),
       Sw(kT4, kT3, kResultOffset), kSret});
}

// A program that asks the machine timer for one interrupt and takes it.
// The timer's `mtimecmp` register is at `mtimecmp` and the interrupt is
// asked for when the timer has counted to `ticks` (below 2048). The handler
// puts the compare value out of reach again, writes a word to `probe` and
// goes back to sleep. Both addresses are as for StoreWordThenSleep.
inline Program TakeOneTimerInterrupt(std::uint64_t mtimecmp, std::int32_t ticks,
                                     std::uint64_t probe) {
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

// A program that takes interrupts from one device through a PLIC, the way
// an operating system does. It gives the PLIC's source 1 a priority,
// enables it, switches the external interrupt on and sleeps. Its handler
// claims the interrupt from the PLIC, quiets the device at `device` by
// writing to it, tells the PLIC it has completed, and returns to sleep.
// `plic` and `device` are addresses as for StoreWordThenSleep.
inline Program HandleInterruptsThroughAPlic(std::uint64_t plic,
                                            std::uint64_t device) {
  Program program;
  const std::size_t auipc_at = program.size();
  program.push_back(Auipc(kT2, 0));
  const std::size_t addi_at = program.size();
  program.push_back(0);  // filled in below, once the handler's place is known
  program.push_back(Csrw(kMtvec, kT2));
  // Source 1: priority 1, at the PLIC's offset 4.
  program.push_back(Lui(kT3, static_cast<Word>(plic >> 12)));
  program.push_back(Li(kT1, 1));
  program.push_back(Sw(kT1, kT3, 4));
  // Source 1's enable bit, at offset 0x2000.
  program.push_back(Lui(kT3, static_cast<Word>((plic + 0x2000) >> 12)));
  program.push_back(Li(kT1, 1 << 1));
  program.push_back(Sw(kT1, kT3, 0));
  // t4 = offset 0x20'0000, where the threshold is, and the claim register
  // 4 further on. The threshold stays at 0.
  program.push_back(Lui(kT4, static_cast<Word>((plic + 0x20'0000) >> 12)));
  program.push_back(Li(kT1, 1));
  program.push_back(Slli(kT1, kT1, kMachineExternalInterrupt));
  program.push_back(Csrs(kMie, kT1));
  program.push_back(Li(kT1, 1 << kInterruptsOn));
  program.push_back(Csrs(kMstatus, kT1));
  AppendSleepForEver(program);

  const std::size_t handler_at = program.size();
  program.push_back(Lw(kT1, kT4, 4));  // claim
  program.push_back(Lui(kT0, static_cast<Word>(device >> 12)));
  program.push_back(Sw(kZero, kT0, 0));  // quiet the device
  program.push_back(Sw(kT1, kT4, 4));    // complete
  program.push_back(kMret);

  program[addi_at] =
      Addi(kT2, kT2, static_cast<std::int32_t>((handler_at - auipc_at) * 4));
  return program;
}

}  // namespace riscv

#endif  // TESTS_CPP_SUPPORT_RISCV_PROGRAM_H_
