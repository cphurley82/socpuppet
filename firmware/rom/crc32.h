/*
 * The sum the boot ROM checks an image by: CRC-32, the one zip files and
 * Ethernet frames carry, and what Python's zlib.crc32() gives.
 */
#ifndef SOCPUPPET_FIRMWARE_ROM_CRC32_H_
#define SOCPUPPET_FIRMWARE_ROM_CRC32_H_

#include <stdint.h>

/* The CRC-32 of `length` bytes from `address` on. */
uint32_t crc32(uintptr_t address, uint32_t length);

#endif /* SOCPUPPET_FIRMWARE_ROM_CRC32_H_ */
