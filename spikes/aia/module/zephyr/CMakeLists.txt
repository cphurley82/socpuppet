# The drivers for the devices of a socpuppet platform that Zephyr has no
# driver of its own for.
zephyr_sources_ifdef(CONFIG_SOCPUPPET_PCIE
  ${CMAKE_CURRENT_LIST_DIR}/../drivers/pcie/socpuppet_pcie.c)
zephyr_sources_ifdef(CONFIG_SOCPUPPET_MAP_WITHOUT_MMU
  ${CMAKE_CURRENT_LIST_DIR}/../drivers/pcie/map_without_mmu.c)

# The drivers for the three devices of a socpuppet SSD, for its firmware.
zephyr_include_directories(${CMAKE_CURRENT_LIST_DIR}/../include)
zephyr_sources_ifdef(CONFIG_SOCPUPPET_NVME_FRONTEND
  ${CMAKE_CURRENT_LIST_DIR}/../drivers/ssd/nvme_frontend.c)
zephyr_sources_ifdef(CONFIG_SOCPUPPET_DMA_ENGINE
  ${CMAKE_CURRENT_LIST_DIR}/../drivers/ssd/dma_engine.c)
zephyr_sources_ifdef(CONFIG_SOCPUPPET_FLASH_CONTROLLER
  ${CMAKE_CURRENT_LIST_DIR}/../drivers/ssd/flash_controller.c)

# The driver for one end of a socpuppet die-to-die link, for the firmware
# on the die that manages it.
zephyr_sources_ifdef(CONFIG_SOCPUPPET_UCIE_LINK
  ${CMAKE_CURRENT_LIST_DIR}/../drivers/d2d/ucie_link.c)

# irq_enable() and its two friends for a SoC with an IMSIC. Zephyr's own
# cannot be defined a second time, so the linker wraps them.
if(CONFIG_SOCPUPPET_AIA_IRQ)
  zephyr_sources(${CMAKE_CURRENT_LIST_DIR}/../drivers/interrupt_controller/aia_irq.c)
  zephyr_ld_options(
    -Wl,--wrap=arch_irq_enable
    -Wl,--wrap=arch_irq_disable
    -Wl,--wrap=arch_irq_is_enabled)
endif()
