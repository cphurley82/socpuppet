#ifndef SPIKES_ISS_INHOUSE_HART_H_
#define SPIKES_ISS_INHOUSE_HART_H_

#include <array>
#include <concepts>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <optional>
#include <span>
#include <type_traits>

#include "spikes/iss/inhouse/compressed.h"

// A minimal RISC-V hart, for the ISS spike: the in-house candidate.
//
// "Hart" is RISC-V's word for one hardware thread: a program counter, 32
// registers, and the rule for what each instruction does to them. This one
// knows the base integer instructions (I), multiply and divide (M), atomics
// (A) and compressed instructions (C), for 32 or 64 bits, in machine mode
// only. That is what Zephyr's hello_world is compiled for.
//
// It is plain C++ with no simulator in it. Memory is whatever Bus it is
// given, and time is whoever calls Run().
//
// What it leaves out: user and supervisor modes, virtual memory, floating
// point, and enforcement of physical memory protection (the PMP registers
// can be written and read back, and nothing checks an access against them).
namespace spike::inhouse {

// How the hart reaches memory and devices. Each call returns false if
// nothing answered at that address.
class Bus {
 public:
  virtual ~Bus() = default;
  virtual bool Read(std::uint64_t address, std::span<std::byte> data) = 0;
  virtual bool Write(std::uint64_t address,
                     std::span<const std::byte> data) = 0;
};

// Why a trap was taken: what the hart writes to `mcause`.
inline constexpr unsigned kInstructionAccessFault = 1;
inline constexpr unsigned kIllegalInstruction = 2;
inline constexpr unsigned kBreakpoint = 3;
inline constexpr unsigned kLoadAccessFault = 5;
inline constexpr unsigned kStoreAccessFault = 7;
inline constexpr unsigned kEnvironmentCallFromMachineMode = 11;
// Interrupts, which are also bit numbers in `mip` and `mie`.
inline constexpr unsigned kMachineSoftwareInterrupt = 3;
inline constexpr unsigned kMachineTimerInterrupt = 7;
inline constexpr unsigned kMachineExternalInterrupt = 11;

// An integer twice as wide as a register, for the high half of a product.
template <typename Reg>
struct Wider;
template <>
struct Wider<std::uint32_t> {
  using Unsigned = std::uint64_t;
  using Signed = std::int64_t;
};
template <>
struct Wider<std::uint64_t> {
  // 128-bit integers are a compiler extension, and say so if asked to be
  // pedantic about the standard.
  __extension__ typedef unsigned __int128 Unsigned;
  __extension__ typedef __int128 Signed;
};

// Division as RISC-V defines it, where nothing traps: dividing by zero
// gives all ones (and the dividend as remainder), and the one signed
// division that overflows gives the dividend back (and no remainder).
template <std::unsigned_integral T>
constexpr T DivideSigned(T a, T b) {
  using S = std::make_signed_t<T>;
  if (b == 0) return static_cast<T>(~T{0});
  if (static_cast<S>(a) == std::numeric_limits<S>::min() &&
      static_cast<S>(b) == -1) {
    return a;
  }
  return static_cast<T>(static_cast<S>(a) / static_cast<S>(b));
}
template <std::unsigned_integral T>
constexpr T RemainderSigned(T a, T b) {
  using S = std::make_signed_t<T>;
  if (b == 0) return a;
  if (static_cast<S>(a) == std::numeric_limits<S>::min() &&
      static_cast<S>(b) == -1) {
    return 0;
  }
  return static_cast<T>(static_cast<S>(a) % static_cast<S>(b));
}
template <std::unsigned_integral T>
constexpr T DivideUnsigned(T a, T b) {
  return b == 0 ? static_cast<T>(~T{0}) : static_cast<T>(a / b);
}
template <std::unsigned_integral T>
constexpr T RemainderUnsigned(T a, T b) {
  return b == 0 ? a : static_cast<T>(a % b);
}

// `Reg` is the type of a register: std::uint32_t for RV32, std::uint64_t
// for RV64.
template <std::unsigned_integral Reg>
class Hart {
 public:
  using Signed = std::make_signed_t<Reg>;
  static constexpr unsigned kXlen = 8 * sizeof(Reg);

  explicit Hart(Bus& bus) : bus_(bus) {}

  // Puts the hart in the state it has coming out of reset, about to
  // execute the instruction at `pc`.
  void Reset(Reg pc) {
    state_ = {};
    state_.pc = pc;
  }

  // Executes up to `budget` instructions and returns how many it did. It
  // stops early if the hart goes to sleep waiting for an interrupt.
  std::uint64_t Run(std::uint64_t budget) {
    std::uint64_t executed = 0;
    while (executed < budget) {
      TakePendingInterrupt();
      if (state_.asleep) break;
      Step();
      ++executed;
    }
    return executed;
  }

  // Asleep after a `wfi`, until an interrupt it has enabled is pending.
  bool Asleep() const { return state_.asleep; }

  // Sets or clears a pending interrupt, as the wire from an interrupt
  // controller or timer would.
  void SetInterruptPending(unsigned interrupt, bool pending) {
    const Reg bit = Reg{1} << interrupt;
    state_.mip = pending ? (state_.mip | bit) : (state_.mip & ~bit);
  }

  std::uint64_t InstructionsRetired() const { return state_.instret; }
  Reg pc() const { return state_.pc; }
  Reg x(unsigned index) const { return state_.x[index]; }

 private:
  // Bits of `mstatus`. MIE: interrupts are enabled. MPIE: what MIE was
  // before the trap being handled. MPP: the mode before it, always machine.
  static constexpr Reg kMie = Reg{1} << 3;
  static constexpr Reg kMpie = Reg{1} << 7;
  static constexpr Reg kMppMachine = Reg{3} << 11;

  struct State {
    std::array<Reg, 32> x{};
    Reg pc = 0;
    Reg mstatus = 0;
    Reg mie = 0;
    Reg mip = 0;
    Reg mtvec = 0;
    Reg mscratch = 0;
    Reg mepc = 0;
    Reg mcause = 0;
    Reg mtval = 0;
    Reg mcountinhibit = 0;
    std::array<Reg, 16> pmpcfg{};
    std::array<Reg, 64> pmpaddr{};
    std::uint64_t instret = 0;
    bool asleep = false;
    // The address a load-reserved is watching, for store-conditional.
    std::optional<Reg> reservation;
  };

  static constexpr Signed AsSigned(Reg value) {
    return static_cast<Signed>(value);
  }
  // A 32-bit value sign-extended to the width of a register.
  static constexpr Reg Extend32(std::uint32_t value) {
    return static_cast<Reg>(
        static_cast<Signed>(static_cast<std::int32_t>(value)));
  }
  // A value read from memory, sign- or zero-extended as its type says.
  template <typename T>
  static constexpr Reg Extend(T value) {
    if constexpr (std::is_signed_v<T>) {
      return static_cast<Reg>(static_cast<Signed>(value));
    } else {
      return static_cast<Reg>(value);
    }
  }

  // The result of a comparison, as the 1 or 0 it leaves in a register.
  static constexpr Reg Flag(bool condition) {
    return condition ? Reg{1} : Reg{0};
  }

  void Set(std::uint32_t rd, Reg value) {
    if (rd != 0) state_.x[rd] = value;  // x0 is always zero
  }

  template <typename T>
  bool Read(Reg address, T& value) {
    return bus_.Read(address, std::as_writable_bytes(std::span{&value, 1}));
  }
  template <typename T>
  bool Write(Reg address, const T& value) {
    return bus_.Write(address, std::as_bytes(std::span{&value, 1}));
  }

  // ---- Traps ---------------------------------------------------------------

  // Takes a trap: remembers where it happened and why, turns interrupts
  // off, and continues at the handler `mtvec` points to.
  void EnterTrap(Reg cause, Reg value, Reg vector_offset) {
    state_.mepc = state_.pc;
    state_.mcause = cause;
    state_.mtval = value;
    const bool enabled = (state_.mstatus & kMie) != 0;
    state_.mstatus = enabled ? kMpie : Reg{0};
    next_pc_ = (state_.mtvec & ~Reg{3}) + vector_offset;
  }

  // An exception: the instruction at pc could not be carried out.
  void Trap(unsigned cause, Reg value) { EnterTrap(cause, value, 0); }

  void TakePendingInterrupt() {
    const Reg ready = state_.mip & state_.mie;
    if (ready == 0) return;
    state_.asleep = false;
    if ((state_.mstatus & kMie) == 0) return;
    // External before software before timer, as the privileged spec ranks
    // them.
    unsigned interrupt = kMachineTimerInterrupt;
    if ((ready >> kMachineExternalInterrupt) & 1) {
      interrupt = kMachineExternalInterrupt;
    } else if ((ready >> kMachineSoftwareInterrupt) & 1) {
      interrupt = kMachineSoftwareInterrupt;
    }
    // In vectored mode (mtvec's low bit) each interrupt has its own entry.
    const bool vectored = (state_.mtvec & 1) != 0;
    EnterTrap((Reg{1} << (kXlen - 1)) | interrupt, 0,
              vectored ? Reg{4} * interrupt : Reg{0});
    state_.pc = next_pc_;
  }

  // ---- One instruction -----------------------------------------------------

  void Step() {
    std::uint32_t instruction = 0;
    Reg length = 4;
    // Usually four bytes can be read at once. At the very end of a memory
    // only two may be there, which is enough for a compressed instruction.
    if (!Read(state_.pc, instruction)) {
      std::uint16_t half = 0;
      if (!Read(state_.pc, half) || (half & 3) == 3) {
        Trap(kInstructionAccessFault, state_.pc);
        state_.pc = next_pc_;
        return;
      }
      instruction = half;
    }
    if ((instruction & 3) != 3) {
      length = 2;
      const std::uint32_t compressed = instruction & 0xFFFF;
      instruction = Expand(compressed, kXlen);
      if (instruction == 0) {
        Trap(kIllegalInstruction, compressed);
        state_.pc = next_pc_;
        return;
      }
    }
    next_pc_ = state_.pc + length;
    Execute(instruction, length);
    state_.pc = next_pc_;
    ++state_.instret;
  }

  void Illegal(std::uint32_t instruction) {
    Trap(kIllegalInstruction, instruction);
  }

  void Execute(std::uint32_t instruction, Reg length) {
    const std::uint32_t opcode = instruction & 0x7F;
    const std::uint32_t rd = (instruction >> 7) & 0x1F;
    const std::uint32_t funct3 = (instruction >> 12) & 0x7;
    const std::uint32_t rs1 = (instruction >> 15) & 0x1F;
    const std::uint32_t rs2 = (instruction >> 20) & 0x1F;
    const std::uint32_t funct7 = instruction >> 25;
    const Reg a = state_.x[rs1];
    const Reg b = state_.x[rs2];
    const auto as_signed = static_cast<std::int32_t>(instruction);
    // The immediate of the I format: the top twelve bits, sign-extended.
    const Reg immediate = Extend32(static_cast<std::uint32_t>(as_signed >> 20));

    switch (opcode) {
      case 0x37:  // lui
        Set(rd, Extend32(instruction & 0xFFFF'F000));
        break;
      case 0x17:  // auipc
        Set(rd, state_.pc + Extend32(instruction & 0xFFFF'F000));
        break;
      case 0x6F: {  // jal
        const std::uint32_t offset =
            (static_cast<std::uint32_t>(as_signed >> 11) & 0xFFF0'0000) |
            (instruction & 0xFF000) | ((instruction >> 9) & 0x800) |
            ((instruction >> 20) & 0x7FE);
        Set(rd, state_.pc + length);
        next_pc_ = state_.pc + Extend32(offset);
        break;
      }
      case 0x67:  // jalr
        if (funct3 != 0) return Illegal(instruction);
        next_pc_ = (a + immediate) & ~Reg{1};
        Set(rd, state_.pc + length);
        break;
      case 0x63: {  // branches
        bool taken = false;
        switch (funct3) {
          case 0:
            taken = a == b;
            break;
          case 1:
            taken = a != b;
            break;
          case 4:
            taken = AsSigned(a) < AsSigned(b);
            break;
          case 5:
            taken = AsSigned(a) >= AsSigned(b);
            break;
          case 6:
            taken = a < b;
            break;
          case 7:
            taken = a >= b;
            break;
          default:
            return Illegal(instruction);
        }
        if (taken) {
          const std::uint32_t offset =
              (static_cast<std::uint32_t>(as_signed >> 19) & 0xFFFF'F000) |
              ((instruction & 0x80) << 4) | ((instruction >> 20) & 0x7E0) |
              ((instruction >> 7) & 0x1E);
          next_pc_ = state_.pc + Extend32(offset);
        }
        break;
      }
      case 0x03: {  // loads
        const Reg address = a + immediate;
        switch (funct3) {
          case 0:
            return Load<std::int8_t>(rd, address);
          case 1:
            return Load<std::int16_t>(rd, address);
          case 2:
            return Load<std::int32_t>(rd, address);
          case 4:
            return Load<std::uint8_t>(rd, address);
          case 5:
            return Load<std::uint16_t>(rd, address);
          case 3:
            if (kXlen == 64) return Load<std::uint64_t>(rd, address);
            return Illegal(instruction);
          case 6:
            if (kXlen == 64) return Load<std::uint32_t>(rd, address);
            return Illegal(instruction);
          default:
            return Illegal(instruction);
        }
      }
      case 0x23: {  // stores
        const Reg address =
            a + Extend32((static_cast<std::uint32_t>(as_signed >> 20) &
                          0xFFFF'FFE0) |
                         rd);
        switch (funct3) {
          case 0:
            return Store<std::uint8_t>(address, b);
          case 1:
            return Store<std::uint16_t>(address, b);
          case 2:
            return Store<std::uint32_t>(address, b);
          case 3:
            if (kXlen == 64) return Store<std::uint64_t>(address, b);
            return Illegal(instruction);
          default:
            return Illegal(instruction);
        }
      }
      case 0x13: {  // arithmetic with an immediate
        const unsigned shift = (instruction >> 20) & (kXlen - 1);
        // What is left above the shift amount says which shift it is.
        const std::uint32_t shift_kind =
            instruction >> (kXlen == 64 ? 26 : 25) << (kXlen == 64 ? 1 : 0);
        switch (funct3) {
          case 0:
            Set(rd, a + immediate);
            break;
          case 2:
            Set(rd, Flag(AsSigned(a) < AsSigned(immediate)));
            break;
          case 3:
            Set(rd, Flag(a < immediate));
            break;
          case 4:
            Set(rd, a ^ immediate);
            break;
          case 6:
            Set(rd, a | immediate);
            break;
          case 7:
            Set(rd, a & immediate);
            break;
          case 1:
            if (shift_kind != 0) return Illegal(instruction);
            Set(rd, a << shift);
            break;
          default:
            if (shift_kind == 0) {
              Set(rd, a >> shift);
            } else if (shift_kind == 0x20) {
              Set(rd, static_cast<Reg>(AsSigned(a) >> shift));
            } else {
              return Illegal(instruction);
            }
        }
        break;
      }
      case 0x33:  // arithmetic between registers
        if (funct7 == 1) return MultiplyOrDivide(instruction, rd, funct3, a, b);
        if (funct7 != 0 && funct7 != 0x20) return Illegal(instruction);
        if (funct7 == 0x20 && funct3 != 0 && funct3 != 5) {
          return Illegal(instruction);
        }
        switch (funct3) {
          case 0:
            Set(rd, funct7 == 0 ? a + b : a - b);
            break;
          case 1:
            Set(rd, a << (b & (kXlen - 1)));
            break;
          case 2:
            Set(rd, Flag(AsSigned(a) < AsSigned(b)));
            break;
          case 3:
            Set(rd, Flag(a < b));
            break;
          case 4:
            Set(rd, a ^ b);
            break;
          case 5:
            Set(rd, funct7 == 0
                        ? a >> (b & (kXlen - 1))
                        : static_cast<Reg>(AsSigned(a) >> (b & (kXlen - 1))));
            break;
          case 6:
            Set(rd, a | b);
            break;
          default:
            Set(rd, a & b);
        }
        break;
      case 0x1B:  // 32-bit arithmetic with an immediate, on a 64-bit hart
      case 0x3B:  // 32-bit arithmetic between registers, on a 64-bit hart
        if (kXlen != 64) return Illegal(instruction);
        return Execute32BitOperation(instruction);
      case 0x0F:  // fence, fence.i: there are no caches here to synchronize
        break;
      case 0x2F:  // atomics
        if (funct3 == 2) return Atomic<std::uint32_t>(instruction, rd, a, b);
        if (funct3 == 3 && kXlen == 64) {
          return Atomic<std::uint64_t>(instruction, rd, a, b);
        }
        return Illegal(instruction);
      case 0x73:  // system
        if (funct3 == 0) return Privileged(instruction);
        return ControlAndStatus(instruction, rd, funct3, rs1);
      default:
        return Illegal(instruction);
    }
  }

  template <typename T>
  void Load(std::uint32_t rd, Reg address) {
    T value{};
    if (!Read(address, value)) return Trap(kLoadAccessFault, address);
    Set(rd, Extend(value));
  }

  template <typename T>
  void Store(Reg address, Reg value) {
    if (!Write(address, static_cast<T>(value))) {
      Trap(kStoreAccessFault, address);
    }
  }

  // The M extension.
  void MultiplyOrDivide(std::uint32_t instruction, std::uint32_t rd,
                        std::uint32_t funct3, Reg a, Reg b) {
    using Wide = typename Wider<Reg>::Unsigned;
    using SignedWide = typename Wider<Reg>::Signed;
    switch (funct3) {
      case 0:  // mul
        Set(rd, a * b);
        break;
      case 1:  // mulh: the high half of signed times signed
        Set(rd, static_cast<Reg>((static_cast<SignedWide>(AsSigned(a)) *
                                  static_cast<SignedWide>(AsSigned(b))) >>
                                 kXlen));
        break;
      case 2:  // mulhsu: signed times unsigned
        Set(rd, static_cast<Reg>((static_cast<SignedWide>(AsSigned(a)) *
                                  static_cast<SignedWide>(b)) >>
                                 kXlen));
        break;
      case 3:  // mulhu: unsigned times unsigned
        Set(rd, static_cast<Reg>(
                    (static_cast<Wide>(a) * static_cast<Wide>(b)) >> kXlen));
        break;
      case 4:
        Set(rd, DivideSigned(a, b));
        break;
      case 5:
        Set(rd, DivideUnsigned(a, b));
        break;
      case 6:
        Set(rd, RemainderSigned(a, b));
        break;
      case 7:
        Set(rd, RemainderUnsigned(a, b));
        break;
      default:
        Illegal(instruction);
    }
  }

  // The "W" instructions of RV64: work on the low 32 bits and sign-extend
  // the result.
  void Execute32BitOperation(std::uint32_t instruction) {
    const std::uint32_t rd = (instruction >> 7) & 0x1F;
    const std::uint32_t funct3 = (instruction >> 12) & 0x7;
    const std::uint32_t funct7 = instruction >> 25;
    const bool with_immediate = (instruction & 0x7F) == 0x1B;
    const auto a =
        static_cast<std::uint32_t>(state_.x[(instruction >> 15) & 0x1F]);
    const auto b =
        with_immediate
            ? static_cast<std::uint32_t>(
                  static_cast<std::int32_t>(instruction) >> 20)
            : static_cast<std::uint32_t>(state_.x[(instruction >> 20) & 0x1F]);
    const std::uint32_t shift = b & 0x1F;
    std::uint32_t result = 0;
    if (!with_immediate && funct7 == 1) {
      switch (funct3) {
        case 0:
          result = a * b;
          break;
        case 4:
          result = DivideSigned(a, b);
          break;
        case 5:
          result = DivideUnsigned(a, b);
          break;
        case 6:
          result = RemainderSigned(a, b);
          break;
        case 7:
          result = RemainderUnsigned(a, b);
          break;
        default:
          return Illegal(instruction);
      }
    } else {
      // For shifts, and for add against subtract, the top seven bits say
      // which. An addiw has its immediate there instead.
      const bool is_shift = funct3 == 1 || funct3 == 5;
      const bool plain = with_immediate && !is_shift;
      if (!plain && funct7 != 0 && funct7 != 0x20) return Illegal(instruction);
      const bool alternate = !plain && funct7 == 0x20;
      switch (funct3) {
        case 0:
          result = alternate ? a - b : a + b;
          break;
        case 1:
          if (alternate) return Illegal(instruction);
          result = a << shift;
          break;
        case 5:
          result = alternate ? static_cast<std::uint32_t>(
                                   static_cast<std::int32_t>(a) >> shift)
                             : a >> shift;
          break;
        default:
          return Illegal(instruction);
      }
    }
    Set(rd, Extend32(result));
  }

  // The A extension: read, modify and write as one step, and the
  // load-reserved and store-conditional pair. With one hart and nothing
  // running between its instructions, "atomic" comes for free.
  template <typename T>
  void Atomic(std::uint32_t instruction, std::uint32_t rd, Reg address,
              Reg operand) {
    using SignedT = std::make_signed_t<T>;
    const std::uint32_t operation = instruction >> 27;
    if (operation == 0x03) {  // store-conditional
      const bool reserved = state_.reservation == address;
      state_.reservation.reset();
      if (!reserved) return Set(rd, 1);
      if (!Write(address, static_cast<T>(operand))) {
        return Trap(kStoreAccessFault, address);
      }
      return Set(rd, 0);
    }
    T old{};
    if (!Read(address, old)) return Trap(kLoadAccessFault, address);
    if (operation == 0x02) {  // load-reserved
      state_.reservation = address;
      return Set(rd, Extend(static_cast<SignedT>(old)));
    }
    const T value = static_cast<T>(operand);
    T result{};
    switch (operation) {
      case 0x01:  // amoswap
        result = value;
        break;
      case 0x00:  // amoadd
        result = static_cast<T>(old + value);
        break;
      case 0x04:  // amoxor
        result = old ^ value;
        break;
      case 0x0C:  // amoand
        result = old & value;
        break;
      case 0x08:  // amoor
        result = old | value;
        break;
      case 0x10:  // amomin
        result = static_cast<SignedT>(old) < static_cast<SignedT>(value)
                     ? old
                     : value;
        break;
      case 0x14:  // amomax
        result = static_cast<SignedT>(old) > static_cast<SignedT>(value)
                     ? old
                     : value;
        break;
      case 0x18:  // amominu
        result = old < value ? old : value;
        break;
      case 0x1C:  // amomaxu
        result = old > value ? old : value;
        break;
      default:
        return Illegal(instruction);
    }
    if (!Write(address, result)) return Trap(kStoreAccessFault, address);
    Set(rd, Extend(static_cast<SignedT>(old)));
  }

  void Privileged(std::uint32_t instruction) {
    switch (instruction) {
      case 0x0000'0073:  // ecall
        return Trap(kEnvironmentCallFromMachineMode, 0);
      case 0x0010'0073:  // ebreak
        return Trap(kBreakpoint, state_.pc);
      case 0x3020'0073: {  // mret: go back to where the trap came from
        const bool was_enabled = (state_.mstatus & kMpie) != 0;
        state_.mstatus = kMpie | (was_enabled ? kMie : Reg{0});
        next_pc_ = state_.mepc;
        return;
      }
      case 0x1050'0073:  // wfi: sleep until an enabled interrupt is pending
        state_.asleep = (state_.mip & state_.mie) == 0;
        return;
      default:
        return Illegal(instruction);
    }
  }

  // ---- Control and status registers ---------------------------------------

  void ControlAndStatus(std::uint32_t instruction, std::uint32_t rd,
                        std::uint32_t funct3, std::uint32_t rs1) {
    const std::uint32_t csr = instruction >> 20;
    // The operand is a register, or the register number itself as a small
    // immediate.
    const Reg operand = (funct3 & 4) != 0 ? Reg{rs1} : state_.x[rs1];
    const std::uint32_t operation = funct3 & 3;  // 1 write, 2 set, 3 clear
    if (operation == 0) return Illegal(instruction);
    Reg old = 0;
    if (!ReadCsr(csr, old)) return Illegal(instruction);
    if (operation == 1 || rs1 != 0) {
      // The top two bits of a CSR's number say whether it is read-only.
      if ((csr >> 10) == 3) return Illegal(instruction);
      WriteCsr(csr, operation == 1   ? operand
                    : operation == 2 ? old | operand
                                     : old & ~operand);
    }
    Set(rd, old);
  }

  // Returns false if there is no such register.
  bool ReadCsr(std::uint32_t csr, Reg& value) const {
    if (csr >= 0x3A0 && csr <= 0x3AF) {
      // On a 64-bit hart only the even-numbered pmpcfg registers exist.
      if (kXlen == 64 && (csr & 1) != 0) return false;
      value = state_.pmpcfg[csr - 0x3A0];
      return true;
    }
    if (csr >= 0x3B0 && csr <= 0x3EF) {
      value = state_.pmpaddr[csr - 0x3B0];
      return true;
    }
    switch (csr) {
      case 0x300:  // mstatus
        value = state_.mstatus | kMppMachine;
        return true;
      case 0x301:  // misa: the word size, and the letters I, M, A and C
        value = (Reg{kXlen == 64 ? 2U : 1U} << (kXlen - 2)) | Reg{0x1105};
        return true;
      case 0x304:
        value = state_.mie;
        return true;
      case 0x305:
        value = state_.mtvec;
        return true;
      case 0x310:  // mstatush, the upper half of mstatus on a 32-bit hart
        value = 0;
        return kXlen == 32;
      case 0x320:
        value = state_.mcountinhibit;
        return true;
      case 0x340:
        value = state_.mscratch;
        return true;
      case 0x341:
        value = state_.mepc;
        return true;
      case 0x342:
        value = state_.mcause;
        return true;
      case 0x343:
        value = state_.mtval;
        return true;
      case 0x344:
        value = state_.mip;
        return true;
      case 0xB00:  // mcycle: one cycle per instruction here
      case 0xB02:  // minstret
        value = static_cast<Reg>(state_.instret);
        return true;
      case 0xB80:  // their upper halves, on a 32-bit hart
      case 0xB82:
        value = static_cast<Reg>(state_.instret >> 32);
        return kXlen == 32;
      case 0xF11:  // mvendorid, marchid, mimpid, mhartid, mconfigptr
      case 0xF12:
      case 0xF13:
      case 0xF14:
      case 0xF15:
        value = 0;
        return true;
      default:
        return false;
    }
  }

  void WriteCsr(std::uint32_t csr, Reg value) {
    if (csr >= 0x3A0 && csr <= 0x3AF) {
      state_.pmpcfg[csr - 0x3A0] = value;
      return;
    }
    if (csr >= 0x3B0 && csr <= 0x3EF) {
      state_.pmpaddr[csr - 0x3B0] = value;
      return;
    }
    switch (csr) {
      case 0x300:
        state_.mstatus = value & (kMie | kMpie);
        break;
      case 0x304:  // only the three machine interrupts can be enabled
        state_.mie = value & ((Reg{1} << kMachineSoftwareInterrupt) |
                              (Reg{1} << kMachineTimerInterrupt) |
                              (Reg{1} << kMachineExternalInterrupt));
        break;
      case 0x305:
        state_.mtvec = value & ~Reg{2};
        break;
      case 0x320:
        state_.mcountinhibit = value;
        break;
      case 0x340:
        state_.mscratch = value;
        break;
      case 0x341:
        state_.mepc = value & ~Reg{1};
        break;
      case 0x342:
        state_.mcause = value;
        break;
      case 0x343:
        state_.mtval = value;
        break;
      default:
        // misa, mip and the counters accept a write and keep their value.
        break;
    }
  }

  Bus& bus_;
  State state_;
  // Where the instruction being executed leaves the program counter.
  Reg next_pc_ = 0;
};

}  // namespace spike::inhouse

#endif  // SPIKES_ISS_INHOUSE_HART_H_
