# Zephyr's stock linker script for RISC-V is all a socpuppet SoC needs.
set(SOC_LINKER_SCRIPT ${ZEPHYR_BASE}/include/zephyr/arch/riscv/common/linker.ld CACHE INTERNAL "")

# For <soc.h>.
zephyr_include_directories(.)

# sys_reboot()'s last step, which Zephyr leaves to a SoC: a write to the
# system controller, for a board whose devicetree has one.
zephyr_sources_ifdef(CONFIG_SOCPUPPET_REBOOT reboot.c)
