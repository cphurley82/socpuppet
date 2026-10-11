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
 */

#include <zephyr/drivers/interrupt_controller/riscv_imsic.h>
#include <zephyr/irq.h>

/* The first number that is an identity of the IMSIC's. */
#define FIRST_IDENTITY 16

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
	riscv_imsic_enable_eiid(irq);
}

void __wrap_arch_irq_disable(unsigned int irq)
{
	if (irq < FIRST_IDENTITY) {
		__real_arch_irq_disable(irq);
		return;
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
