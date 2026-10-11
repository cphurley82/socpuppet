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

#if DT_HAS_COMPAT_STATUS_OKAY(riscv_aplic)

#include <zephyr/drivers/interrupt_controller/riscv_aplic.h>
#include <zephyr/sw_isr_table.h>
#include <zephyr/sys/sys_io.h>
#include <zephyr/sys/util.h>

#define APLIC             DT_COMPAT_GET_ANY_STATUS_OKAY(riscv_aplic)
/* The APLIC's sources are numbered from 1 to this. */
#define LAST_SOURCE       DT_PROP(APLIC, riscv_num_sources)
/*
 * The register that has the APLIC look at a source again (the
 * specification's setipnum_le), which Zephyr's header has no name for.
 */
#define APLIC_SETIPNUM_LE 0x2000

/* The handler each source's driver connected, by the source's number. */
static struct _isr_table_entry handlers[LAST_SOURCE + 1];

/*
 * Runs a source's handler and then has the APLIC look at the source again.
 *
 * An APLIC sends a message when a source's line rises, and a device may
 * still be asking when its handler returns: a UART with room to transmit,
 * whose handler only saw to the byte that had come in. Its line never
 * fell, so nothing rises and no message follows. Asked to look again, the
 * APLIC sends one if the line is still high. Linux's driver does the same
 * after each handler, and Zephyr's does not (see docs/upstream.md in
 * socpuppet), so the source's place in the interrupt table is taken by
 * this, with the driver's own handler behind it.
 */
static void handle_and_look_again(const void *arg)
{
	unsigned int source = POINTER_TO_UINT(arg);

	handlers[source].isr(handlers[source].arg);
	sys_write32(source, DT_REG_ADDR(APLIC) + APLIC_SETIPNUM_LE);
}

/*
 * Makes a source ready to be enabled: its handler behind the one above,
 * its mode, and where its interrupt goes. Nothing can interrupt through it
 * yet, at the APLIC or at the IMSIC.
 *
 * The handler is swapped in the table by hand. Zephyr's own way to do it
 * (z_isr_install) is for an interrupt that is not enabled, which it asks
 * through irq_is_enabled, and would chain the two handlers where
 * interrupts are shared. A driver that connects another handler after it
 * has enabled its interrupt takes this one's place until it enables again.
 */
static void set_up_source(unsigned int source)
{
	const struct device *aplic = riscv_aplic_get_dev();
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

static void enable_source(unsigned int source)
{
	riscv_aplic_enable_src(riscv_aplic_get_dev(), source, true);
}

static void disable_source(unsigned int source)
{
	riscv_aplic_enable_src(riscv_aplic_get_dev(), source, false);
}

#else /* no APLIC */

#define LAST_SOURCE 0

static void set_up_source(unsigned int source)
{
	ARG_UNUSED(source);
}

static void enable_source(unsigned int source)
{
	ARG_UNUSED(source);
}

static void disable_source(unsigned int source)
{
	ARG_UNUSED(source);
}

#endif /* DT_HAS_COMPAT_STATUS_OKAY(riscv_aplic) */

/* Zephyr's own, by the names the linker gives what it wraps. */
void __real_arch_irq_enable(unsigned int irq);
void __real_arch_irq_disable(unsigned int irq);
int __real_arch_irq_is_enabled(unsigned int irq);

void __wrap_arch_irq_enable(unsigned int irq)
{
	if (irq < FIRST_IDENTITY) {
		__real_arch_irq_enable(irq);
		return;
	}
	/*
	 * The APLIC's enable comes last: with it a line that is already
	 * asking sends at once, and by then the IMSIC has to be listening.
	 */
	if (irq <= LAST_SOURCE) {
		set_up_source(irq);
	}
	riscv_imsic_enable_eiid(irq);
	if (irq <= LAST_SOURCE) {
		enable_source(irq);
	}
}

void __wrap_arch_irq_disable(unsigned int irq)
{
	if (irq < FIRST_IDENTITY) {
		__real_arch_irq_disable(irq);
		return;
	}
	if (irq <= LAST_SOURCE) {
		disable_source(irq);
	}
	riscv_imsic_disable_eiid(irq);
}

int __wrap_arch_irq_is_enabled(unsigned int irq)
{
	if (irq < FIRST_IDENTITY) {
		return __real_arch_irq_is_enabled(irq);
	}
	return riscv_imsic_is_enabled(irq);
}
