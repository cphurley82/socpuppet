/*
 * Where a CPU starts when its reset vector is the boot ROM.
 *
 * A ROM has no memory of its own to write to, so the stack is at the top
 * of the RAM the image is about to be copied into the bottom of. Anything
 * that traps here stops the CPU, and so does a ROM that has nothing to
 * jump to, once it has said so.
 */
/* board_rv64.h or board_rv32.h, which the build includes for it. */

	.section .text.start, "ax"
	.globl _start
_start:
	la	t0, halt
	csrw	mtvec, t0
	li	sp, STACK_TOP
	call	rom_main
	/* rom_main returns when there is no image to jump to. */

	/*
	 * A trap vector's address has its low two bits clear: in mtvec they
	 * say how the vector is used.
	 */
	.balign	4
halt:
	wfi
	j	halt
