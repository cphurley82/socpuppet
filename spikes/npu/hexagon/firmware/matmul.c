/*
 * The Hexagon candidate's program: what runs on the DSP. It waits at the
 * doorbell's accelerator face for a command, reads the descriptor the host
 * left in memory, multiplies, writes the product back and writes COMPLETE,
 * which is what raises the host's interrupt. Then it waits for the next.
 *
 * Bare metal, no C library: compiled with clang's Hexagon back end,
 * started by start.S. The register offsets are spikes/npu/doorbell.h's.
 *
 * The core polls PENDING. A real program would sleep until its interrupt
 * controller (the L2VIC) woke it on the doorbell's `kick` line; wiring
 * that is the next step after this spike, and polling shows the same
 * thing about the slot.
 */
#include <stdint.h>

#define DOORBELL 0x50000000u
#define DOORBELL_DESCRIPTOR_LOW 0x0Cu
#define DOORBELL_DESCRIPTOR_HIGH 0x10u
#define DOORBELL_PENDING 0x14u
#define DOORBELL_COMPLETE 0x18u
#define DOORBELL_COMPLETE_DONE 1u
#define DOORBELL_COMPLETE_ERROR 2u

/* The host's memory is at the same addresses on the DSP's bus. */
struct descriptor {
  uint64_t a;
  uint64_t b;
  uint64_t c;
  uint32_t m;
  uint32_t k;
  uint32_t n;
  uint32_t reserved;
};

static uint32_t read_register(uint32_t offset) {
  return *(volatile uint32_t*)(DOORBELL + offset);
}

static void write_register(uint32_t offset, uint32_t value) {
  *(volatile uint32_t*)(DOORBELL + offset) = value;
}

/* A 32-bit core: an address above 4 GiB is one it cannot reach. */
static int fits(uint64_t address) { return (address >> 32) == 0; }

static uint32_t multiply(const struct descriptor* job) {
  if (!fits(job->a) || !fits(job->b) || !fits(job->c)) {
    return DOORBELL_COMPLETE_ERROR;
  }
  const int8_t* a = (const int8_t*)(uint32_t)job->a;
  const int8_t* b = (const int8_t*)(uint32_t)job->b;
  int32_t* c = (int32_t*)(uint32_t)job->c;
  for (uint32_t row = 0; row < job->m; ++row) {
    for (uint32_t column = 0; column < job->n; ++column) {
      int32_t sum = 0;
      for (uint32_t inner = 0; inner < job->k; ++inner) {
        sum += (int32_t)a[row * job->k + inner] *
               (int32_t)b[inner * job->n + column];
      }
      c[row * job->n + column] = sum;
    }
  }
  return DOORBELL_COMPLETE_DONE;
}

void serve(void) {
  for (;;) {
    while (read_register(DOORBELL_PENDING) == 0) {
    }
    const uint32_t low = read_register(DOORBELL_DESCRIPTOR_LOW);
    const uint32_t high = read_register(DOORBELL_DESCRIPTOR_HIGH);
    if (high != 0) {
      write_register(DOORBELL_COMPLETE, DOORBELL_COMPLETE_ERROR);
      continue;
    }
    write_register(DOORBELL_COMPLETE, multiply((const struct descriptor*)low));
  }
}
