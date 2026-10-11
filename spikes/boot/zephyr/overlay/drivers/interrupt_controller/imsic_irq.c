/*
 * irq_enable(), irq_disable() and irq_is_enabled() for a socpuppet SoC
 * whose interrupts arrive at an IMSIC.
 *
 * An IMSIC is the interrupt controller a RISC-V hart is sent messages at.
 * A device interrupts by writing a number, an interrupt identity, to the
 * IMSIC's page, and the IMSIC then raises the hart's external interrupt
 * line. Zephyr's driver for it takes the identity as the interrupt's
 * number, in one table with the CPU's own lines.
 *
 * Zephyr's own three (soc/common/riscv-privileged/soc_common_irq.c) know
 * the CPU's lines and a PLIC's sources, and nothing of an IMSIC. Given an
 * identity they set a bit of the `mie` register that has nothing to do
 * with it, and the identity stays switched off in the IMSIC. Their file
 * is built into every RISC-V SoC of this kind, so they cannot be defined a
 * second time. The linker is told to wrap them instead (--wrap, in this
 * module's CMakeLists.txt), which sends every call to the functions here.
 * See docs/upstream.md in socpuppet.
 *
 * The numbers are one space. Below 16 is a line of the CPU's own: 7 is the
 * machine timer's, and 11 the IMSIC's. From 16 up is an identity. An IMSIC
 * has identities 1 to 15 as well, and Zephyr has no number for them,
 * since theirs are the CPU's lines. A board gives none of them to a device.
 *
 * A device that only has a wire has it at an APLIC, which sends a message
 * to the IMSIC for it. Zephyr's APLIC driver has the functions to set a
 * source up and nothing calls them, so that is done here too: a number
 * that is one of the APLIC's sources is that source, and it is told to
 * send the identity of the same number. One number is then the interrupt
 * all the way, in the devicetree, at the APLIC and at the IMSIC.
 */

#include <zephyr/devicetree.h>
#include <zephyr/drivers/interrupt_controller/riscv_imsic.h>
#include <zephyr/irq.h>

/* The first number that is an identity of the IMSIC's. */
#define FIRST_IDENTITY 16

#if DT_HAS_COMPAT_STATUS_OKAY(socpuppet_aplic)

#include <zephyr/device.h>
#include <zephyr/drivers/interrupt_controller/riscv_aplic.h>
#include <zephyr/sw_isr_table.h>
#include <zephyr/sys/sys_io.h>
#include <zephyr/sys/util.h>

/*
 * The register that has an APLIC look at a source again (the
 * specification's setipnum_le), which Zephyr's header has no name for.
 */
#define APLIC_SETIPNUM_LE 0x2000

/* The APLIC a source is on: its driver's device, and its registers. */
struct aplic {
  const struct device* dev;
  mem_addr_t base;
};

/*
 * Which APLIC has each number, by the number. A board can have more than
 * one APLIC, each with sources 1 to 31, so a number does not say whose
 * source it is. The devicetree does: each APLIC's node lists the sources
 * that have a device's line on them (socpuppet,sources), and a board
 * gives no number to two of them.
 *
 * The array is as long as the highest number listed, and a number no
 * APLIC lists has no device here: it is an identity for a message from
 * somewhere else.
 */
#define SOURCE_OF(node, prop, idx) \
  [DT_PROP_BY_IDX(node, prop, idx)] = {DEVICE_DT_GET(node), DT_REG_ADDR(node)},
#define SOURCES_OF(node) \
  DT_FOREACH_PROP_ELEM(node, socpuppet_sources, SOURCE_OF)

static const struct aplic aplic_of[] = {
    [0] = {NULL, 0}, DT_FOREACH_STATUS_OKAY(socpuppet_aplic, SOURCES_OF)};

/* The handler each source's driver connected, by the source's number. */
static struct _isr_table_entry handlers[ARRAY_SIZE(aplic_of)];

static bool is_a_source(unsigned int irq) {
  return irq < ARRAY_SIZE(aplic_of) && aplic_of[irq].dev != NULL;
}

static void handle_and_look_again(const void* arg) {
  unsigned int source = POINTER_TO_UINT(arg);

  handlers[source].isr(handlers[source].arg);
  sys_write32(source, aplic_of[source].base + APLIC_SETIPNUM_LE);
}

static void set_up_source(unsigned int source) {
  const struct device* aplic = aplic_of[source].dev;
  unsigned int key = irq_lock();

  if (_sw_isr_table[source].isr != handle_and_look_again) {
    handlers[source] = _sw_isr_table[source];
    _sw_isr_table[source].arg = UINT_TO_POINTER(source);
    _sw_isr_table[source].isr = handle_and_look_again;
  }
  irq_unlock(key);
  /* Every line in a socpuppet platform asks while it is high. */
  riscv_aplic_config_src(aplic, source, APLIC_SM_LEVEL_HIGH);
  /* To hart 0, as the identity of the source's own number. */
  riscv_aplic_msi_route(aplic, source, 0, source);
}

static void enable_source(unsigned int source) {
  riscv_aplic_enable_src(aplic_of[source].dev, source, true);
}

static void disable_source(unsigned int source) {
  riscv_aplic_enable_src(aplic_of[source].dev, source, false);
}

#else /* no APLIC */

static bool is_a_source(unsigned int irq) {
  ARG_UNUSED(irq);
  return false;
}

static void set_up_source(unsigned int source) { ARG_UNUSED(source); }

static void enable_source(unsigned int source) { ARG_UNUSED(source); }

static void disable_source(unsigned int source) { ARG_UNUSED(source); }

#endif /* DT_HAS_COMPAT_STATUS_OKAY(socpuppet_aplic) */

/* Zephyr's own, by the names the linker gives what it wraps. */
void __real_arch_irq_enable(unsigned int irq);
void __real_arch_irq_disable(unsigned int irq);
int __real_arch_irq_is_enabled(unsigned int irq);

void __wrap_arch_irq_enable(unsigned int irq) {
  if (irq < FIRST_IDENTITY) {
    __real_arch_irq_enable(irq);
    return;
  }
  /*
   * The APLIC's enable comes last: with it a line that is already
   * asking sends at once, and by then the IMSIC has to be listening.
   */
  if (is_a_source(irq)) {
    set_up_source(irq);
  }
  riscv_imsic_enable_eiid(irq);
  if (is_a_source(irq)) {
    enable_source(irq);
  }
}

void __wrap_arch_irq_disable(unsigned int irq) {
  if (irq < FIRST_IDENTITY) {
    __real_arch_irq_disable(irq);
    return;
  }
  if (is_a_source(irq)) {
    disable_source(irq);
  }
  riscv_imsic_disable_eiid(irq);
}

int __wrap_arch_irq_is_enabled(unsigned int irq) {
  if (irq < FIRST_IDENTITY) {
    return __real_arch_irq_is_enabled(irq);
  }
  return riscv_imsic_is_enabled(irq);
}
