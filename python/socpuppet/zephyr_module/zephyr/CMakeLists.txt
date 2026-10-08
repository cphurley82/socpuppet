# The drivers for the devices of a socpuppet platform that Zephyr has no
# driver of its own for.
zephyr_sources_ifdef(CONFIG_SOCPUPPET_PCIE
  ${CMAKE_CURRENT_LIST_DIR}/../drivers/pcie/socpuppet_pcie.c)
zephyr_sources_ifdef(CONFIG_SOCPUPPET_MAP_WITHOUT_MMU
  ${CMAKE_CURRENT_LIST_DIR}/../drivers/pcie/map_without_mmu.c)
