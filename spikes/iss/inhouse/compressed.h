#ifndef SPIKES_ISS_INHOUSE_COMPRESSED_H_
#define SPIKES_ISS_INHOUSE_COMPRESSED_H_

#include <cstdint>

// The C extension: 16-bit encodings of the commonest instructions.
//
// Every compressed instruction stands for exactly one ordinary 32-bit
// instruction, so the hart does not execute them itself. It expands each
// into the 32-bit instruction it stands for and executes that.
namespace spike::inhouse {

// Builders for the 32-bit encodings, by format.
constexpr std::uint32_t EncodeR(std::uint32_t funct7, std::uint32_t rs2,
                                std::uint32_t rs1, std::uint32_t funct3,
                                std::uint32_t rd, std::uint32_t opcode) {
  return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) |
         (rd << 7) | opcode;
}
constexpr std::uint32_t EncodeI(std::uint32_t immediate, std::uint32_t rs1,
                                std::uint32_t funct3, std::uint32_t rd,
                                std::uint32_t opcode) {
  return ((immediate & 0xFFF) << 20) | (rs1 << 15) | (funct3 << 12) |
         (rd << 7) | opcode;
}
constexpr std::uint32_t EncodeS(std::uint32_t immediate, std::uint32_t rs2,
                                std::uint32_t rs1, std::uint32_t funct3,
                                std::uint32_t opcode) {
  return (((immediate >> 5) & 0x7F) << 25) | (rs2 << 20) | (rs1 << 15) |
         (funct3 << 12) | ((immediate & 0x1F) << 7) | opcode;
}
constexpr std::uint32_t EncodeB(std::uint32_t offset, std::uint32_t rs2,
                                std::uint32_t rs1, std::uint32_t funct3) {
  return (((offset >> 12) & 1) << 31) | (((offset >> 5) & 0x3F) << 25) |
         (rs2 << 20) | (rs1 << 15) | (funct3 << 12) |
         (((offset >> 1) & 0xF) << 8) | (((offset >> 11) & 1) << 7) | 0x63;
}
constexpr std::uint32_t EncodeJ(std::uint32_t offset, std::uint32_t rd) {
  return (((offset >> 20) & 1) << 31) | (((offset >> 1) & 0x3FF) << 21) |
         (((offset >> 11) & 1) << 20) | (((offset >> 12) & 0xFF) << 12) |
         (rd << 7) | 0x6F;
}

// The low `bits` bits of `value`, sign-extended to 32.
constexpr std::uint32_t SignExtend(std::uint32_t value, unsigned bits) {
  const std::uint32_t sign = std::uint32_t{1} << (bits - 1);
  return (value ^ sign) - sign;
}

// The 32-bit instruction that the compressed instruction `c` stands for,
// on a hart of the given word size. Zero if `c` is not a valid compressed
// instruction (zero is not a valid 32-bit instruction either).
constexpr std::uint32_t Expand(std::uint32_t c, unsigned xlen) {
  constexpr std::uint32_t kSp = 2;
  // The registers named in full, and the three-bit ones that mean x8-x15.
  const std::uint32_t rd = (c >> 7) & 0x1F;
  const std::uint32_t rs2 = (c >> 2) & 0x1F;
  const std::uint32_t rd_short = 8 + ((c >> 2) & 0x7);
  const std::uint32_t rs1_short = 8 + ((c >> 7) & 0x7);
  // The six-bit immediate most forms carry: c[12] and c[6:2].
  const std::uint32_t imm6 = ((c >> 7) & 0x20) | ((c >> 2) & 0x1F);
  const std::uint32_t simm6 = SignExtend(imm6, 6);
  const std::uint32_t funct3 = (c >> 13) & 0x7;

  switch (c & 0x3) {
    case 0: {
      const std::uint32_t word_offset =
          ((c >> 7) & 0x38) | ((c >> 4) & 0x4) | ((c << 1) & 0x40);
      const std::uint32_t double_offset = ((c >> 7) & 0x38) | ((c << 1) & 0xC0);
      switch (funct3) {
        case 0: {  // c.addi4spn: addi rd', sp, nzuimm
          const std::uint32_t immediate = ((c >> 7) & 0x30) |
                                          ((c >> 1) & 0x3C0) |
                                          ((c >> 4) & 0x4) | ((c >> 2) & 0x8);
          if (immediate == 0) return 0;
          return EncodeI(immediate, kSp, 0, rd_short, 0x13);
        }
        case 2:  // c.lw
          return EncodeI(word_offset, rs1_short, 2, rd_short, 0x03);
        case 3:  // c.ld (64-bit only)
          if (xlen != 64) return 0;
          return EncodeI(double_offset, rs1_short, 3, rd_short, 0x03);
        case 6:  // c.sw
          return EncodeS(word_offset, rd_short, rs1_short, 2, 0x23);
        case 7:  // c.sd (64-bit only)
          if (xlen != 64) return 0;
          return EncodeS(double_offset, rd_short, rs1_short, 3, 0x23);
        default:
          return 0;
      }
    }
    case 1: {
      const std::uint32_t jump_offset = SignExtend(
          ((c >> 1) & 0x800) | ((c >> 7) & 0x10) | ((c >> 1) & 0x300) |
              ((c << 2) & 0x400) | ((c >> 1) & 0x40) | ((c << 1) & 0x80) |
              ((c >> 2) & 0xE) | ((c << 3) & 0x20),
          12);
      const std::uint32_t branch_offset = SignExtend(
          ((c >> 4) & 0x100) | ((c >> 7) & 0x18) | ((c << 1) & 0xC0) |
              ((c >> 2) & 0x6) | ((c << 3) & 0x20),
          9);
      switch (funct3) {
        case 0:  // c.addi
          return EncodeI(simm6, rd, 0, rd, 0x13);
        case 1:
          if (xlen == 32) return EncodeJ(jump_offset, 1);  // c.jal
          if (rd == 0) return 0;
          return EncodeI(simm6, rd, 0, rd, 0x1B);  // c.addiw
        case 2:                                    // c.li
          return EncodeI(simm6, 0, 0, rd, 0x13);
        case 3:
          if (rd == kSp) {  // c.addi16sp
            const std::uint32_t immediate = SignExtend(
                ((c >> 3) & 0x200) | ((c >> 2) & 0x10) | ((c << 1) & 0x40) |
                    ((c << 4) & 0x180) | ((c << 3) & 0x20),
                10);
            if (immediate == 0) return 0;
            return EncodeI(immediate, kSp, 0, kSp, 0x13);
          }
          if (imm6 == 0) return 0;
          return ((simm6 & 0xFFFFF) << 12) | (rd << 7) | 0x37;  // c.lui
        case 4: {
          if (xlen == 32 && (imm6 & 0x20) != 0 && ((c >> 10) & 0x3) < 2) {
            return 0;  // a shift by 32 or more on a 32-bit hart
          }
          switch ((c >> 10) & 0x3) {
            case 0:  // c.srli
              return EncodeI(imm6, rs1_short, 5, rs1_short, 0x13);
            case 1:  // c.srai
              return EncodeI(0x400 | imm6, rs1_short, 5, rs1_short, 0x13);
            case 2:  // c.andi
              return EncodeI(simm6, rs1_short, 7, rs1_short, 0x13);
            default: {
              const std::uint32_t which = (c >> 5) & 0x3;
              if ((c & 0x1000) == 0) {
                switch (which) {
                  case 0:  // c.sub
                    return EncodeR(0x20, rd_short, rs1_short, 0, rs1_short,
                                   0x33);
                  case 1:  // c.xor
                    return EncodeR(0, rd_short, rs1_short, 4, rs1_short, 0x33);
                  case 2:  // c.or
                    return EncodeR(0, rd_short, rs1_short, 6, rs1_short, 0x33);
                  default:  // c.and
                    return EncodeR(0, rd_short, rs1_short, 7, rs1_short, 0x33);
                }
              }
              if (xlen != 64) return 0;
              if (which == 0) {  // c.subw
                return EncodeR(0x20, rd_short, rs1_short, 0, rs1_short, 0x3B);
              }
              if (which == 1) {  // c.addw
                return EncodeR(0, rd_short, rs1_short, 0, rs1_short, 0x3B);
              }
              return 0;
            }
          }
        }
        case 5:  // c.j
          return EncodeJ(jump_offset, 0);
        case 6:  // c.beqz
          return EncodeB(branch_offset, 0, rs1_short, 0);
        default:  // c.bnez
          return EncodeB(branch_offset, 0, rs1_short, 1);
      }
    }
    case 2:
      switch (funct3) {
        case 0:  // c.slli
          if (xlen == 32 && (imm6 & 0x20) != 0) return 0;
          return EncodeI(imm6, rd, 1, rd, 0x13);
        case 2:  // c.lwsp
          if (rd == 0) return 0;
          return EncodeI(
              ((c >> 7) & 0x20) | ((c >> 2) & 0x1C) | ((c << 4) & 0xC0), kSp, 2,
              rd, 0x03);
        case 3:  // c.ldsp (64-bit only)
          if (xlen != 64 || rd == 0) return 0;
          return EncodeI(
              ((c >> 7) & 0x20) | ((c >> 2) & 0x18) | ((c << 4) & 0x1C0), kSp,
              3, rd, 0x03);
        case 4:
          if ((c & 0x1000) == 0) {
            if (rs2 == 0) {  // c.jr
              if (rd == 0) return 0;
              return EncodeI(0, rd, 0, 0, 0x67);
            }
            return EncodeR(0, rs2, 0, 0, rd, 0x33);  // c.mv
          }
          if (rs2 == 0) {
            if (rd == 0) return 0x0010'0073;    // c.ebreak
            return EncodeI(0, rd, 0, 1, 0x67);  // c.jalr
          }
          return EncodeR(0, rs2, rd, 0, rd, 0x33);  // c.add
        case 6:                                     // c.swsp
          return EncodeS(((c >> 7) & 0x3C) | ((c >> 1) & 0xC0), rs2, kSp, 2,
                         0x23);
        case 7:  // c.sdsp (64-bit only)
          if (xlen != 64) return 0;
          return EncodeS(((c >> 7) & 0x38) | ((c >> 1) & 0x1C0), rs2, kSp, 3,
                         0x23);
        default:
          return 0;
      }
    default:
      return 0;  // not compressed: the low two bits are 11
  }
}

}  // namespace spike::inhouse

#endif  // SPIKES_ISS_INHOUSE_COMPRESSED_H_
