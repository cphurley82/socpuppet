/*
 * Where a CPU starts when its reset vector is the boot ROM.
 *
 * A ROM has no memory of its own to write to, so the stack is at the top
 * of the RAM the image is about to be copied into the bottom of. A trap
 * here is said on the console and stops the CPU, and so does a ROM that
 * has nothing to jump to, once it has said so.
 */
/* board_rv64.h or board_rv32.h, which the build includes for it. */

	.section .text.start, "ax"
	.globl _start
_start:
	la	t0, trapped
	csrw	mtvec, t0
	li	sp, STACK_TOP
	call	rom_main
	/* rom_main returns when there is no image to jump to. */
	j	halt

	/*
	 * A trap vector's address has its low two bits clear: in mtvec they
	 * say how the vector is used.
	 *
	 * The CPU says why it trapped, at which instruction, and for an
	 * access that was refused at which address. Saying so starts on a
	 * new stack: nothing is gone back to, and the program that trapped
	 * may have left none. The vector goes to `halt` first, so that a
	 * trap in the saying, as there would be with no UART or no RAM, puts
	 * the CPU to sleep there. With the vector left here it would trap
	 * again and again, which says no more and keeps a simulator busy.
	 */
	.balign	4
trapped:
	la	t0, halt
	csrw	mtvec, t0
	li	sp, STACK_TOP
	csrr	a0, mcause
	csrr	a1, mepc
	csrr	a2, mtval
	call	rom_trapped
	/* rom_trapped returns when it has said so. */
	j	halt

	.balign	4
halt:
	wfi
	j	halt
