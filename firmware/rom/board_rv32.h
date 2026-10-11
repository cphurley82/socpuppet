/*
 * Where a 32-bit socpuppet CPU has the three things its boot ROM uses: the
 * kit that the SSD's CPU and the IO die's manager share.
 * tests/python/test_rom_firmware.py holds each to the kit.
 */
#ifndef SOCPUPPET_FIRMWARE_ROM_BOARD_RV32_H_
#define SOCPUPPET_FIRMWARE_ROM_BOARD_RV32_H_

/* The console: a 16550 UART, its registers a byte apart. */
#define UART_BASE   0x10000000
/* The system controller, which says where the image is. */
#define SYSCON_BASE 0x00100000
/* One byte past the end of the SRAM, which is where the ROM's stack starts. */
#define STACK_TOP   0x20040000

#endif /* SOCPUPPET_FIRMWARE_ROM_BOARD_RV32_H_ */
