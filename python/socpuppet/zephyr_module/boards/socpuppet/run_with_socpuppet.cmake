# Zephyr's `run` target for a socpuppet board: the image just built, run by
# `socpuppet run` on the board it was built for, its console on standard
# output. `west build -t run` uses it, and so does twister, Zephyr's test
# runner, which reads the console for a verdict.
#
# `custom` is Zephyr's name for an emulator it knows nothing of. Its `run`
# target then depends on a `run_custom` that the board defines.
set(SUPPORTED_EMU_PLATFORMS custom)

set(socpuppet_run_arguments --board ${BOARD})
foreach(shield ${SHIELD_AS_LIST})
  list(APPEND socpuppet_run_arguments --shield ${shield})
endforeach()

add_custom_target(run_custom
  COMMAND socpuppet run ${APPLICATION_BINARY_DIR}/zephyr/${KERNEL_ELF_NAME}
          ${socpuppet_run_arguments}
  # The console goes straight to whoever is reading, a line at a time,
  # where ninja would otherwise keep it until the run is over.
  USES_TERMINAL)

# The image is built before it is run. Zephyr reads a board.cmake before it
# has named the target that builds the image, so the dependency is added at
# the end of the configuration, when the variable has its value.
cmake_language(DEFER CALL add_dependencies run_custom
               ${logical_target_for_zephyr_elf})
