/* The ROM is one block of read-only memory, with nothing that is written. */
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

	/* A ROM cannot be written, so a program for one has no data. */
	.data : { *(.data .data.* .sdata .sdata.*) } > rom
	.bss : { *(.bss .bss.* .sbss .sbss.* COMMON) } > rom
	ASSERT(SIZEOF(.data) == 0, "The ROM has initialized data, and nowhere to keep it.")
	ASSERT(SIZEOF(.bss) == 0, "The ROM has zeroed data, and nowhere to keep it.")

	/DISCARD/ : { *(.comment) *(.riscv.attributes) *(.note.*) *(.eh_frame) }
}
