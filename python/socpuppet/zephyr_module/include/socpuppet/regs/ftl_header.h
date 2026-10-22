/*
 * FTL header: the registers.
 *
 * The first page of the reserve: whose table follows it, and where the next
 * page the drive is written to goes.
 *
 * Generated from regs/ftl_header.rdl by tools/regs.py. Do not edit: change
 * the register map and run `uv run python tools/lint.py --fix`.
 */

#ifndef SOCPUPPET_REGS_FTL_HEADER_H_
#define SOCPUPPET_REGS_FTL_HEADER_H_

/* How many bytes of address space the block takes. */
#define FTL_HEADER_SIZE 0x10U

/*
 * What says this is the FTL's header at all. A NAND never programmed reads
 * all ones here, and holds a drive of zeros.
 */
#define FTL_HEADER_MAGIC        0x00U
/* The four bytes `SFTL`, which as a little-endian number is 0x4C544653. */
#define FTL_HEADER_MAGIC_NUMBER 1280591443U

/* Which layout the table that follows is in. */
#define FTL_HEADER_VERSION       0x04U
/*
 * The header, then the table from the reserve's second page: for each page of
 * the drive, the NAND page that holds it, a 32-bit word, all ones for none.
 */
#define FTL_HEADER_VERSION_FIRST 1U

/*
 * How many pages the drive has, and so how many entries the table: a table
 * for a drive of another size is not this one's.
 */
#define FTL_HEADER_PAGES 0x08U

/*
 * The next NAND page nobody has: where the next page of the drive that no
 * NAND page holds yet is written.
 */
#define FTL_HEADER_NEXT_FREE 0x0CU

#endif /* SOCPUPPET_REGS_FTL_HEADER_H_ */
