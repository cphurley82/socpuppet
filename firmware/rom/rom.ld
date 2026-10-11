/*
 * A boot ROM is one block of memory that can be read and not written, so
 * all of the program goes in it and none of the program may be data.
 */
ENTRY(_start)

MEMORY
{
	rom (rx) : ORIGIN = 0x1000, LENGTH = 60K
}

SECTIONS
{
	.text : {
		KEEP(*(.text.start))
		*(.text .text.*)
		*(.rodata .rodata.* .srodata .srodata.*)
	} > rom

	/* What would have to be written to has nowhere to be kept. */
	.data : { *(.data .data.* .sdata .sdata.*) } > rom
	.bss : { *(.bss .bss.* .sbss .sbss.* COMMON) } > rom
	ASSERT(SIZEOF(.data) == 0, "The ROM has initialized data, and nowhere to keep it.")
	ASSERT(SIZEOF(.bss) == 0, "The ROM has zeroed data, and nowhere to keep it.")

	/DISCARD/ : { *(.comment) *(.riscv.attributes) *(.note.*) *(.eh_frame) }
}
