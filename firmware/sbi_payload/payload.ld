/*
 * The payload runs where OpenSBI's fw_jump jumps on the generic platform:
 * 2 MiB into the host's RAM, which is where a kernel would be.
 */
ENTRY(_start)

MEMORY
{
	ram (rwx) : ORIGIN = 0x80200000, LENGTH = 1M
}

SECTIONS
{
	.text : {
		KEEP(*(.text.start))
		*(.text .text.*)
	} > ram
	.rodata : { *(.rodata .rodata.* .srodata .srodata.*) } > ram
	.data : { *(.data .data.* .sdata .sdata.*) } > ram
	/*
	 * Zeroed by start.S, eight bytes at a time, and the stack after it.
	 * Both are past the end of what is loaded, where Python lays out the
	 * devicetree for fw_jump (socpuppet.opensbi): harmless, since fw_jump
	 * copies the devicetree away before it jumps here.
	 */
	.bss : ALIGN(8) {
		bss_start = .;
		*(.bss .bss.* .sbss .sbss.* COMMON)
		. = ALIGN(8);
		bss_end = .;
		. = ALIGN(16);
		. += 4096;
		stack_top = .;
	} > ram

	/DISCARD/ : { *(.comment) *(.riscv.attributes) *(.note.*) *(.eh_frame) }
}
