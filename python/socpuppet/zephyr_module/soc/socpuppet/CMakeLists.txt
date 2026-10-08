# Zephyr's stock linker script for RISC-V is all a socpuppet SoC needs.
set(SOC_LINKER_SCRIPT ${ZEPHYR_BASE}/include/zephyr/arch/riscv/common/linker.ld CACHE INTERNAL "")

# For <soc.h>.
zephyr_include_directories(.)
