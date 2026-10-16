/*
 * Where the payload starts, in supervisor mode, with what OpenSBI hands
 * every next stage: the hart's number in a0 and the address of the
 * devicetree in a1. They are passed straight on to payload_main.
 *
 * The trap handler is installed first, so that whatever traps after this
 * is said. OpenSBI loads the payload as its file has it, which leaves out
 * the zeros of .bss, so they are written here, as C expects them.
 */
	.section .text.start, "ax"
	.globl _start
_start:
	la	t0, payload_trapped
	csrw	stvec, t0
	la	sp, stack_top
	la	t0, bss_start
	la	t1, bss_end
1:	bgeu	t0, t1, 2f
	sd	zero, 0(t0)
	addi	t0, t0, 8
	j	1b
2:	call	payload_main
	/* payload_main returns when the reset it asked for did not come. */
3:	wfi
	j	3b
