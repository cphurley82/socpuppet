/*
 * Boot image header: the registers.
 *
 * What a boot image starts with: what the program after it is, where it goes,
 * and a sum to check it by.
 *
 * Generated from regs/boot_image_header.rdl by tools/regs.py. Do not edit:
 * change the register map and run `uv run python tools/lint.py --fix`.
 */

#ifndef SOCPUPPET_REGS_BOOT_IMAGE_HEADER_H_
#define SOCPUPPET_REGS_BOOT_IMAGE_HEADER_H_

/* How many bytes of address space the block takes. */
#define BOOT_IMAGE_HEADER_SIZE 0x48U

/* What says this is an image at all. */
#define BOOT_IMAGE_HEADER_MAGIC        0x00U
/* The four bytes `SOCP`, which as a little-endian number is 0x50434F53. */
#define BOOT_IMAGE_HEADER_MAGIC_NUMBER 1346588499U

/*
 * Which kind of CPU the program was built for, by the width of its registers
 * in bits.
 */
#define BOOT_IMAGE_HEADER_XLEN      0x04U
/* A program for a 32-bit CPU. */
#define BOOT_IMAGE_HEADER_XLEN_RV32 32U
/* A program for a 64-bit CPU. */
#define BOOT_IMAGE_HEADER_XLEN_RV64 64U

/* Where in memory the program's first byte goes, the low 32 bits. */
#define BOOT_IMAGE_HEADER_LOAD_ADDRESS_LOW 0x08U

/* The high 32 bits, which are zero for a 32-bit CPU. */
#define BOOT_IMAGE_HEADER_LOAD_ADDRESS_HIGH 0x0CU

/*
 * Where the CPU starts executing once the program is in memory, the low 32
 * bits.
 */
#define BOOT_IMAGE_HEADER_ENTRY_LOW 0x10U

/* The high 32 bits. */
#define BOOT_IMAGE_HEADER_ENTRY_HIGH 0x14U

/* How many bytes the program is: what follows the header. */
#define BOOT_IMAGE_HEADER_LENGTH 0x18U

/*
 * The CRC-32 of the program's bytes, as zlib and Ethernet compute it. The
 * header is not in it.
 */
#define BOOT_IMAGE_HEADER_CRC 0x1CU

/*
 * The image's name, as text, for a boot ROM to say which image it could not
 * start. Up to 32 bytes of UTF-8, with zeros after a shorter one. A name of
 * all 32 bytes has no zero after it.
 */
#define BOOT_IMAGE_HEADER_NAME      0x20U
#define BOOT_IMAGE_HEADER_NAME_SIZE 0x20U

/*
 * What the boot ROM hands the program in `a1`, the low 32 bits: for OpenSBI,
 * the address of its devicetree. Zero for nothing. The hart's number goes in
 * `a0`.
 */
#define BOOT_IMAGE_HEADER_ARGUMENT_LOW 0x40U

/* The high 32 bits, which a 32-bit CPU does not hand on. */
#define BOOT_IMAGE_HEADER_ARGUMENT_HIGH 0x44U

#endif /* SOCPUPPET_REGS_BOOT_IMAGE_HEADER_H_ */
