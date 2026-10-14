#ifndef SPIKES_SPEED_LOOPS_H_
#define SPIKES_SPEED_LOOPS_H_

#include <cstdint>

#include "tests/cpp/support/riscv_program.h"

// The speed spike's three programs (milestone M26), made of the CPU
// tests' assembler and nothing else. Each one stores a word that is not
// zero as its result once its loop is done, and then sleeps, so that a
// harness can tell a finished run from one that is still going.
namespace speed {

// A program and what running it to its result costs, worked out from its
// shape: the instructions it executes and the page-table walks it makes.
struct Loop {
  riscv::Program program;
  std::uint64_t instructions;
  std::uint64_t walks;
};

// M1's counted loop, the one in riscv::CountDownThenSleep: two
// instructions each time round, which ask nothing of the bus but their
// fetch. It runs wherever it is loaded, with paging off, and leaves its
// result kResultOffset past its first instruction.
inline Loop Counted(riscv::Word iterations) {
  using riscv::Addi, riscv::Auipc, riscv::Bne, riscv::kT0, riscv::kT1,
      riscv::kT2, riscv::kZero, riscv::Li, riscv::Lui, riscv::Sw;
  riscv::Program program{Auipc(kT0, 0),      Lui(kT2, iterations >> 12),
                         Addi(kT2, kT2, -1), Bne(kT2, kZero, -4),
                         Li(kT1, 1),         Sw(kT1, kT0, kResultOffset)};
  riscv::AppendSleepForEver(program);
  return {.program = program,
          .instructions = (2 * std::uint64_t{iterations}) + 4,
          .walks = 0};
}

// Where the paging loops' data is: `pages` pages of 4 KiB, one after the
// other from `first` up, every one of them mapped readable.
struct DataPages {
  std::uint64_t first;
  std::uint64_t pages;
};

// The paging loops: supervisor mode under Sv39 at the virtual addresses
// `at` says, loading a doubleword from each of `data`'s pages in turn,
// `rounds` times over, and storing one at `at.result` when it is done.
// With `empty_the_tlb` each round ends in an `sfence.vma`, so that every
// load of the next is a walk of the page tables, and so is the first
// fetch from the code's page. Without it the round ends in a `nop` there
// and every translation after the first round is one the hart kept.
inline Loop Paging(const riscv::Pages& at, const DataPages& data,
                   riscv::Word rounds, bool empty_the_tlb) {
  using riscv::Addi, riscv::Bne, riscv::kT1, riscv::kT2, riscv::kT3, riscv::kT4,
      riscv::kT5, riscv::kT6, riscv::kZero, riscv::Ld, riscv::Li, riscv::Lui,
      riscv::Sd, riscv::Sub;
  riscv::Assembler program;
  riscv::AppendEnterSupervisorModeUnderPaging(program, at);
  // t3 counts the rounds down, t6 is minus a page, for Sub to step by.
  program.Emit({Lui(kT3, rounds >> 12), Lui(kT6, 0xF'FFFF)});
  const std::uint64_t round_at = program.Here();
  program.Load(kT4, data.first);
  program.Emit(Li(kT5, static_cast<std::int32_t>(data.pages)));
  const std::uint64_t page_at = program.Here();
  program.Emit({Ld(kT1, kT4, 0), Sub(kT4, kT4, kT6), Addi(kT5, kT5, -1)});
  program.Emit(Bne(kT5, kZero,
                   static_cast<std::int32_t>(page_at) -
                       static_cast<std::int32_t>(program.Here())));
  program.Emit(empty_the_tlb ? riscv::kSfenceVma : Addi(kZero, kZero, 0));
  program.Emit(Addi(kT3, kT3, -1));
  program.Emit(Bne(kT3, kZero,
                   static_cast<std::int32_t>(round_at) -
                       static_cast<std::int32_t>(program.Here())));
  program.Load(kT2, at.result);
  program.Emit({Li(kT1, 1), Sd(kT1, kT2, 0)});
  riscv::AppendSleepForEver(program);

  // A round: the address of the first page (two instructions), the count
  // of pages, four for each page, the fence or the nop, and two to go
  // round again.
  const std::uint64_t per_round = 2 + 1 + (4 * data.pages) + 1 + 2;
  return {.program = program.Assemble(),
          .instructions = rounds * per_round,
          // Every page of data, and the page of code, once a round.
          .walks = empty_the_tlb ? rounds * (data.pages + 1) : 0};
}

}  // namespace speed

#endif  // SPIKES_SPEED_LOOPS_H_
