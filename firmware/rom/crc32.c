/*
 * CRC-32, half a byte at a time.
 *
 * A CRC is the remainder of a long division of the bytes, taken as one
 * very long number, by a fixed one. It is division with no borrowing,
 * where each subtraction is an exclusive-or, which is why the loop below
 * has shifts and exclusive-ors and nothing else. The fixed number is
 * 0x04C11DB7, and it is here as 0xEDB88320, the same bits in the other
 * order, because this CRC takes each byte lowest bit first. A change to
 * any bit of the bytes changes the remainder, which is why a ROM can tell
 * by it that an image is not the one its header was made for.
 *
 * The division can be done a bit at a time with no table, or a byte at a
 * time with a table of 256 remainders, which is twice as fast as this and
 * a kilobyte of numbers nobody can read, in a ROM that is little more
 * than that altogether. This is the usual middle: sixteen remainders,
 * written out, and two steps for each byte. Zephyr's own
 * crc32_ieee_update() does the same.
 */
#include "crc32.h"

uint32_t crc32(uintptr_t address, uint32_t length)
{
	/* What is left of each of the sixteen half bytes, divided. */
	static const uint32_t remainders[16] = {
		0x00000000, 0x1db71064, 0x3b6e20c8, 0x26d930ac, 0x76dc4190, 0x6b6b51f4,
		0x4db26158, 0x5005713c, 0xedb88320, 0xf00f9344, 0xd6d6a3e8, 0xcb61b38c,
		0x9b64c2b0, 0x86d3d2d4, 0xa00ae278, 0xbdbdf21c,
	};
	const uint8_t *bytes = (const uint8_t *)address;
	uint32_t crc = 0xffffffff;

	for (uint32_t at = 0; at < length; at++) {
		crc ^= bytes[at];
		crc = (crc >> 4) ^ remainders[crc & 0xf];
		crc = (crc >> 4) ^ remainders[crc & 0xf];
	}
	return ~crc;
}
