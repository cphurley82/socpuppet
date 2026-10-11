/*
 * Where a CPU starts when its reset vector is the ROM: set a stack up and
 * call C. A ROM has no RAM of its own, so the stack is at the top of the
 * RAM the image is about to be copied into the bottom of.
 */
	.section .text.start, "ax"
	.globl _start
_start:
	li	sp, STACK_TOP
	call	rom_main
1:	wfi
	j	1b
