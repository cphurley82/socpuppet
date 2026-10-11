/*
 * The spike's boot ROM: find an image in the flash, copy it to RAM, jump.
 *
 * The header here is the spike's own, four words, and M14's real one is
 * generated from regs/boot_image.rdl. This is only to see that the Zephyr
 * SDK's compiler builds a program with no Zephyr in it, for both kinds of
 * CPU, and that such a program can start one.
 */
#include <stdint.h>

#define MAGIC 0x50504F53u /* "SOPP", little-endian */

struct header {
  uint32_t magic;
  uint32_t load_address;
  uint32_t entry;
  uint32_t length;
};

/* A 16550's transmit register, and the bit that says it has room. */
#define UART_THR (*(volatile uint8_t*)(UART_BASE + 0))
#define UART_LSR (*(volatile uint8_t*)(UART_BASE + 5))
#define LSR_THRE 0x20

static void say(const char* text) {
  for (; *text != '\0'; text++) {
    while ((UART_LSR & LSR_THRE) == 0) {
    }
    UART_THR = (uint8_t)*text;
  }
}

void rom_main(void) {
  const struct header* header = (const struct header*)FLASH_BASE;
  const uint8_t* from = (const uint8_t*)(header + 1);

  if (header->magic != MAGIC) {
    say("rom: no image\n");
    return;
  }
  uint8_t* to = (uint8_t*)(uintptr_t)header->load_address;

  for (uint32_t i = 0; i < header->length; i++) {
    to[i] = from[i];
  }
  say("rom: jumping\n");
  ((void (*)(void))(uintptr_t)header->entry)();
}
