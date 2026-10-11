/*
 * sys_reboot() for a socpuppet SoC.
 *
 * RISC-V has no common way to reset a system, so Zephyr leaves the last
 * step to the SoC: sys_arch_reboot(), which is an empty function unless a
 * SoC has its own. A socpuppet CPU has a system controller with a register
 * that asks for a reset, so this writes it.
 */

#define DT_DRV_COMPAT socpuppet_system_controller

#include <zephyr/arch/cpu.h>
#include <zephyr/devicetree.h>
#include <zephyr/sys/sys_io.h>
#include <zephyr/sys/util.h>

#include <socpuppet/regs/system_controller.h>

void sys_arch_reboot(int type)
{
	ARG_UNUSED(type);

	sys_write32(SYSTEM_CONTROLLER_RESET_REQUEST_RESET,
		    DT_INST_REG_ADDR(0) + SYSTEM_CONTROLLER_RESET_REQUEST);
	/*
	 * The reset is a pulse the controller is about to give. Coming back
	 * from here would have Zephyr say that the reboot failed.
	 */
	for (;;) {
	}
}
