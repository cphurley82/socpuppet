/*
 * irq_enable(), irq_disable() and irq_is_enabled() for a SoC whose
 * interrupts arrive at an IMSIC.
 *
 * Zephyr's own (soc/common/riscv-privileged/soc_common_irq.c) know the
 * CPU's lines and a PLIC's sources. Given an identity they set a bit of
 * `mie` that has nothing to do with it. The linker is told to wrap them
 * (--wrap, in this module's CMakeLists.txt), which sends every call
 * through the functions here.
 *
 * The numbers are one space. Below 16 is a line of the CPU's own. From 16
 * up is an identity of the IMSIC, and one no bigger than the APLIC's
 * number of sources is also that source of the APLIC, routed to the
 * identity of its own number.
 */

#include <zephyr/device.h>
#include <zephyr/drivers/interrupt_controller/riscv_aplic.h>
#include <zephyr/drivers/interrupt_controller/riscv_imsic.h>
#include <zephyr/init.h>
#include <zephyr/irq.h>

#define FIRST_IDENTITY 16

void __real_arch_irq_enable(unsigned int irq);
void __real_arch_irq_disable(unsigned int irq);
int __real_arch_irq_is_enabled(unsigned int irq);

#ifdef CONFIG_RISCV_APLIC_MSI
static bool is_aplic_source(unsigned int irq)
{
	return irq <= riscv_aplic_get_num_sources(riscv_aplic_get_dev());
}
#else
static bool is_aplic_source(unsigned int irq)
{
	ARG_UNUSED(irq);
	return false;
}
#endif

void __wrap_arch_irq_enable(unsigned int irq)
{
	if (irq < FIRST_IDENTITY) {
		__real_arch_irq_enable(irq);
		return;
	}
	riscv_imsic_enable_eiid(irq);
#ifdef CONFIG_RISCV_APLIC_MSI
	if (is_aplic_source(irq)) {
		const struct device *aplic = riscv_aplic_get_dev();

		riscv_aplic_config_src(aplic, irq, APLIC_SM_LEVEL_HIGH);
		riscv_aplic_msi_route(aplic, irq, 0, irq);
		riscv_aplic_enable_src(aplic, irq, true);
	}
#endif
}

void __wrap_arch_irq_disable(unsigned int irq)
{
	if (irq < FIRST_IDENTITY) {
		__real_arch_irq_disable(irq);
		return;
	}
#ifdef CONFIG_RISCV_APLIC_MSI
	if (is_aplic_source(irq)) {
		riscv_aplic_enable_src(riscv_aplic_get_dev(), irq, false);
	}
#endif
	riscv_imsic_disable_eiid(irq);
}

int __wrap_arch_irq_is_enabled(unsigned int irq)
{
	if (irq < FIRST_IDENTITY) {
		return __real_arch_irq_is_enabled(irq);
	}
	return riscv_imsic_is_enabled(irq);
}
