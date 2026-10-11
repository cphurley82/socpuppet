/*
 * Where the host has the three things its boot ROM uses: socpuppet's one
 * board with a 64-bit CPU. tests/python/test_rom_firmware.py holds each to
 * the board.
 */
#ifndef SOCPUPPET_FIRMWARE_ROM_BOARD_RV64_H_
#define SOCPUPPET_FIRMWARE_ROM_BOARD_RV64_H_

/* The console: a 16550 UART, its registers a byte apart. */
#define UART_BASE   0x10000000
/* The system controller, which says where the image is. */
#define SYSCON_BASE 0x00100000
/* One byte past the end of RAM, which is where the ROM's stack starts. */
#define STACK_TOP   0x84000000

#endif /* SOCPUPPET_FIRMWARE_ROM_BOARD_RV64_H_ */
