/*
 * A payload for OpenSBI: a program in supervisor mode that makes SBI's
 * calls, as a kernel will, and says what each one did. It is what the
 * OpenSBI test reads (tests/python/test_opensbi_boots.py), so every line
 * starts with "payload: " and means one thing.
 *
 * SBI, the Supervisor Binary Interface, is how supervisor mode asks
 * machine mode for what only machine mode can do. A call is an `ecall`
 * with the extension's number in a7, the function's in a6, and the
 * arguments from a0; the error comes back in a0.
 */
#include <stdint.h>

#include <socpuppet/regs/system_controller.h>

/* Where the system controller is comes from the ROM's board_rv64.h, which
 * the build includes ahead of this: the host's addresses for a program
 * with no devicetree reader. */

#define SBI_EXT_TIME     0x54494D45 /* "TIME" */
#define SBI_EXT_SRST     0x53525354 /* "SRST": system reset */
#define SBI_EXT_DBCN     0x4442434E /* "DBCN": debug console */
#define SRST_SHUTDOWN    0
#define SRST_COLD_REBOOT 1

/* The supervisor's timer interrupt: its bit in sie, and its cause. */
#define SIE_STIE               (1UL << 5)
#define SSTATUS_SIE            (1UL << 1)
#define CAUSE_SUPERVISOR_TIMER ((1UL << 63) | 5)

/*
 * How long to ask the timer for, in its ticks: a short while. The host's
 * timer counts 10 million a second, as the devicetree's timebase-frequency
 * says, so this is 1 ms.
 */
#define TICKS 10000

static long sbi_call(long extension, long function, long arg0, long arg1, long arg2)
{
	register long a0 __asm__("a0") = arg0;
	register long a1 __asm__("a1") = arg1;
	register long a2 __asm__("a2") = arg2;
	register long a6 __asm__("a6") = function;
	register long a7 __asm__("a7") = extension;

	__asm__ volatile("ecall" : "+r"(a0), "+r"(a1) : "r"(a2), "r"(a6), "r"(a7) : "memory");
	return a0;
}

/* The debug console's write: the text's length and its address. */
static void say(const char *text)
{
	long length = 0;

	while (text[length] != '\0') {
		length++;
	}
	/* The address in two halves, the high one zero here. */
	sbi_call(SBI_EXT_DBCN, 0, length, (long)text, 0);
}

/* "0x" and a number's hex digits, with no zeros in front. */
static void say_hex(uint64_t number)
{
	char digits[19] = "0x";
	int shift = 60;
	int at = 2;

	while (shift > 0 && ((number >> shift) & 0xF) == 0) {
		shift -= 4;
	}
	for (; shift >= 0; shift -= 4) {
		digits[at++] = "0123456789abcdef"[(number >> shift) & 0xF];
	}
	digits[at] = '\0';
	say(digits);
}

static volatile int timer_interrupted;

/*
 * The supervisor's trap handler, which start.S installs before anything
 * else. The timer's interrupt is expected once: it is switched off in sie,
 * which keeps it from being taken again while the timer still says it is
 * due. Anything else is said and stops here.
 */
__attribute__((interrupt("supervisor"), aligned(4))) void payload_trapped(void)
{
	unsigned long cause;

	__asm__ volatile("csrr %0, scause" : "=r"(cause));
	if (cause == CAUSE_SUPERVISOR_TIMER) {
		__asm__ volatile("csrc sie, %0" : : "r"(SIE_STIE));
		timer_interrupted = 1;
		return;
	}
	say("payload: stopped by a trap: scause ");
	say_hex(cause);
	say("\n");
	for (;;) {
		__asm__ volatile("wfi");
	}
}

/*
 * Asks for a timer interrupt and waits for it. The interrupt is enabled in
 * sie and not in sstatus, so it is only taken where interrupts are let in
 * for a moment, after the wfi it wakes: taken any sooner, between the look
 * at the flag and the wfi, it would leave the wfi nothing to wake for.
 */
static void take_a_timer_interrupt(void)
{
	unsigned long now;

	__asm__ volatile("csrr %0, time" : "=r"(now));
	sbi_call(SBI_EXT_TIME, 0, (long)(now + TICKS), 0, 0);
	__asm__ volatile("csrs sie, %0" : : "r"(SIE_STIE));
	while (!timer_interrupted) {
		__asm__ volatile("wfi");
		__asm__ volatile("csrs sstatus, %0" : : "r"(SSTATUS_SIE));
		__asm__ volatile("csrc sstatus, %0" : : "r"(SSTATUS_SIE));
	}
	say("payload: timer interrupt taken in supervisor mode\n");
}

/* A load of a word from an odd address, which this hart traps on, and
 * which OpenSBI makes on the payload's behalf. */
static void load_a_misaligned_word(void)
{
	static const uint8_t bytes[8]
		__attribute__((aligned(8))) = {0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88};
	uint32_t word;

	__asm__ volatile("lw %0, 1(%1)" : "=r"(word) : "r"(bytes));
	say("payload: misaligned load read ");
	say_hex(word);
	say("\n");
}

static uint32_t reset_cause(void)
{
	return *(const volatile uint32_t *)(SYSCON_BASE + SYSTEM_CONTROLLER_RESET_CAUSE);
}

void payload_main(unsigned long hart, const volatile uint8_t *devicetree)
{
	say("payload: hello from supervisor mode, on hart ");
	say_hex(hart);
	say("\n");

	/* A devicetree starts with its magic number, high byte first. */
	say("payload: devicetree magic ");
	say_hex(((uint32_t)devicetree[0] << 24) | ((uint32_t)devicetree[1] << 16) |
		((uint32_t)devicetree[2] << 8) | devicetree[3]);
	say("\n");

	take_a_timer_interrupt();
	load_a_misaligned_word();

	uint32_t cause = reset_cause();

	say("payload: reset cause ");
	if (cause == SYSTEM_CONTROLLER_RESET_CAUSE_POWER_ON) {
		say("power-on");
	} else if (cause == SYSTEM_CONTROLLER_RESET_CAUSE_WATCHDOG) {
		say("watchdog");
	} else if (cause == SYSTEM_CONTROLLER_RESET_CAUSE_SOFTWARE) {
		say("software");
	} else {
		say_hex(cause);
	}
	say("\n");

	/* Once after the power comes on, and then off. */
	if (cause == SYSTEM_CONTROLLER_RESET_CAUSE_POWER_ON) {
		say("payload: asking for a cold reboot\n");
		sbi_call(SBI_EXT_SRST, 0, SRST_COLD_REBOOT, 0, 0);
	} else {
		say("payload: asking to be switched off\n");
		sbi_call(SBI_EXT_SRST, 0, SRST_SHUTDOWN, 0, 0);
	}
	say("payload: the reset call came back\n");
}
