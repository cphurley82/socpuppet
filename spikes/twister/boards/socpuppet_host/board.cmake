# Twister runs a board's tests through the `run` target, which with a
# custom emulator is this one (cmake/emu/custom.cmake in Zephyr's tree).
set(SUPPORTED_EMU_PLATFORMS custom)
set(socpuppet_run_args --board ${BOARD})
foreach(shield ${SHIELD_AS_LIST})
  list(APPEND socpuppet_run_args --shield ${shield})
endforeach()
add_custom_target(run_custom
  COMMAND socpuppet-run ${APPLICATION_BINARY_DIR}/zephyr/${KERNEL_ELF_NAME}
          ${socpuppet_run_args}
  DEPENDS ${logical_target_for_zephyr_elf}
  WORKING_DIRECTORY ${APPLICATION_BINARY_DIR}
  USES_TERMINAL)
