/*
 * socpuppet's boot ROM: what a CPU runs first when it boots as silicon
 * does. It asks the system controller where its image is, finds the image
 * in the flash, copies it into RAM and jumps to it.
 *
 * It is a zero-stage bootloader, the smallest thing that can start a
 * bigger one, and it has no Zephyr in it: a ROM is written when the chip
 * is made, and has to do with what is there at power-on. That is a UART it
 * can write to without setting anything up, a flash that reads like
 * memory, and no memory of its own but a stack.
 *
 * The image's header is regs/boot_image_header.rdl, which is also what
 * Python writes one from (socpuppet.boot_image).
 */
#include <stdint.h>

#include <socpuppet/regs/boot_image_header.h>
#include <socpuppet/regs/system_controller.h>

#include "crc32.h"

/*
 * Where the UART, the system controller and the top of RAM are comes from
 * board_rv64.h or board_rv32.h, which the build includes ahead of this.
 */

/* A 16550's transmit register, and the bit that says it has room. */
#define UART_THR (*(volatile uint8_t *)(UART_BASE + 0))
#define UART_LSR (*(volatile uint8_t *)(UART_BASE + 5))
#define LSR_THRE 0x20

static uint32_t read32(uintptr_t address)
{
	return *(const volatile uint32_t *)address;
}

static void put(char character)
{
	while ((UART_LSR & LSR_THRE) == 0) {
	}
	UART_THR = (uint8_t)character;
}

static void say(const char *text)
{
	for (; *text != '\0'; text++) {
		put(*text);
	}
}

/* "0x" and a number's hex digits, from the one `shift` bits up, down. */
static void say_digits(uintptr_t number, int shift)
{
	say("0x");
	for (; shift >= 0; shift -= 4) {
		put("0123456789abcdef"[(number >> shift) & 0xF]);
	}
}

/* A number as "0x" and its digits, with no zeros in front. */
static void say_hex(uintptr_t number)
{
	int shift = 8 * sizeof(number) - 4;

	while (shift > 0 && ((number >> shift) & 0xF) == 0) {
		shift -= 4;
	}
	say_digits(number, shift);
}

/* A CRC, which is always written with all eight of its digits. */
static void say_crc(uint32_t crc)
{
	say_digits(crc, 28);
}

static void say_decimal(uint32_t number)
{
	char digits[10];
	int count = 0;

	do {
		digits[count++] = '0' + number % 10;
		number /= 10;
	} while (number != 0);
	while (count > 0) {
		put(digits[--count]);
	}
}

/* The image's name, which has no zero after it when it fills its place. */
static void say_name(uintptr_t header)
{
	const volatile char *name = (const volatile char *)(header + BOOT_IMAGE_HEADER_NAME);

	for (unsigned int at = 0; at < BOOT_IMAGE_HEADER_NAME_SIZE && name[at] != '\0'; at++) {
		put(name[at]);
	}
}

/*
 * An address from its two words in the header. A 32-bit CPU has no use
 * for the high one.
 */
static uintptr_t address_at(uintptr_t low_word)
{
	uintptr_t address = read32(low_word);

#if __riscv_xlen == 64
	address |= (uintptr_t)read32(low_word + 4) << 32;
#endif
	return address;
}

/*
 * A register's width at a time, and what is left a byte at a time. The
 * flash is read through volatile pointers because it is a device: each
 * read is one access of that size, and the compiler may not make a call
 * to memcpy of the loop, which a ROM does not have.
 */
static void copy(uintptr_t to, uintptr_t from, uint32_t length)
{
	uint32_t done = 0;

	for (; length - done >= sizeof(uintptr_t); done += sizeof(uintptr_t)) {
		*(volatile uintptr_t *)(to + done) = *(const volatile uintptr_t *)(from + done);
	}
	for (; done < length; done++) {
		*(volatile uint8_t *)(to + done) = *(const volatile uint8_t *)(from + done);
	}
}

/*
 * What start.S calls when the CPU traps, with the three registers a
 * RISC-V CPU says of a trap in: why (mcause), the address of the
 * instruction it was at (mepc), and one more thing that depends on why
 * (mtval), which for an access that was refused is the address of it. An
 * image that is to be loaded where there is no memory comes here, and so
 * does one that traps before it has a handler of its own.
 */
void rom_trapped(uintptr_t mcause, uintptr_t mepc, uintptr_t mtval)
{
	say("rom: stopped by a trap: mcause ");
	say_hex(mcause);
	say(", mepc ");
	say_hex(mepc);
	say(", mtval ");
	say_hex(mtval);
	say("\n");
}

/* Returns only if there is nothing to jump to, and the CPU then stops. */
void rom_main(void)
{
	uintptr_t header = read32(SYSCON_BASE + SYSTEM_CONTROLLER_BOOT_ADDRESS);

	if (read32(header + BOOT_IMAGE_HEADER_MAGIC) != BOOT_IMAGE_HEADER_MAGIC_NUMBER) {
		say("rom: no image at ");
		say_hex(header);
		say("\n");
		return;
	}

	uint32_t xlen = read32(header + BOOT_IMAGE_HEADER_XLEN);

	if (xlen != __riscv_xlen) {
		say("rom: ");
		say_name(header);
		say(" is a ");
		say_decimal(xlen);
		say("-bit image, and this is a ");
		say_decimal(__riscv_xlen);
		say("-bit CPU\n");
		return;
	}

	uint32_t length = read32(header + BOOT_IMAGE_HEADER_LENGTH);
	uintptr_t load_address = address_at(header + BOOT_IMAGE_HEADER_LOAD_ADDRESS_LOW);
	uintptr_t entry = address_at(header + BOOT_IMAGE_HEADER_ENTRY_LOW);

	copy(load_address, header + BOOT_IMAGE_HEADER_SIZE, length);

	/*
	 * The sum is of what is now in RAM, which is what would run: a byte
	 * that went wrong on the way is caught as one that was wrong in the
	 * flash is.
	 */
	uint32_t expected = read32(header + BOOT_IMAGE_HEADER_CRC);
	uint32_t found = crc32(load_address, length);

	if (found != expected) {
		say("rom: ");
		say_name(header);
		say(": bad CRC: its header says ");
		say_crc(expected);
		say(", and its bytes come to ");
		say_crc(found);
		say("\n");
		return;
	}

	say("rom: ");
	say_name(header);
	say(": ");
	say_decimal(length);
	say(" bytes to ");
	say_hex(load_address);
	say(", jumping to ");
	say_hex(entry);
	say("\n");
	((void (*)(void))entry)();
}
