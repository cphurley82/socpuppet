/*
 * The flash translation layer (FTL): what turns the drive's pages into
 * pages of NAND.
 *
 * The host sees a drive of numbered blocks. A NAND chip has pages, of
 * several blocks each, and no page of it is any block's home: the firmware
 * decides where each page of the drive is kept, and keeps a table of it. An
 * FTL calls that its logical-to-physical table, L2P for short.
 *
 * This one is as small as an FTL can be:
 *
 *   - A page of the drive that was never written is nowhere, and reads as
 *     zeros. (An erased NAND page reads as all ones. The zeros a host
 *     expects of a new drive are the firmware's.)
 *   - A page written for the first time takes the next NAND page nobody
 *     has.
 *   - A page written again is programmed where it is. Only an ideal NAND
 *     allows that: a real one has to be given a fresh page, and the old one
 *     left as rubbish until its block is erased. That is where garbage
 *     collection begins, and where this FTL stops.
 *
 * The table is in the SSD's buffer and nowhere else, so it does not
 * outlive the firmware. A real FTL keeps it on the NAND as well.
 */

#ifndef FIRMWARE_SSD_FTL_H_
#define FIRMWARE_SSD_FTL_H_

#include <stdint.h>

/*
 * Asks the NAND what it is and makes an empty table. Returns 0, or a
 * negative errno if the NAND cannot be used.
 */
int ftl_start(void);

/* How many pages the drive has, and how many bytes one is. */
uint32_t ftl_pages(void);
uint32_t ftl_page_size(void);

/*
 * Puts a page of the drive in the page buffer: from the NAND, or as zeros
 * if it was never written. Returns 0, or a negative errno.
 */
int ftl_load(uint32_t page);

/*
 * Programs the page buffer into the NAND, as a page of the drive. Returns
 * 0, or a negative errno.
 *
 * A write of part of a page is why the page is loaded first: what is not
 * being written has to survive.
 */
int ftl_store(uint32_t page);

#endif /* FIRMWARE_SSD_FTL_H_ */
