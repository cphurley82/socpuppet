# Source patches to DBT-RISE-RISCV, applied in its source directory after
# it is fetched. Written as replacements, so that applying them twice is
# harmless.

# Patch 1: the generated register tables say offsetof(core::regs, core::regs::X0).
# GCC accepts the qualified member name and Clang does not, so drop the
# qualification: offsetof(core::regs, X0).
file(GLOB headers src/iss/arch/*.h)
foreach(file IN LISTS headers)
  file(READ ${file} text)
  string(REGEX REPLACE
    "offsetof\\(([a-z0-9_]+::[A-Za-z0-9_]+), [a-z0-9_]+::[A-Za-z0-9_]+::"
    "offsetof(\\1, " patched "${text}")
  if(NOT patched STREQUAL text)
    file(WRITE ${file} "${patched}")
  endif()
endforeach()

# Patch 2: raising reset a second time. Three things stood in the way of
# the core starting again, all in the SystemC wrapper.
set(file src/sysc/core_complex.cpp)
file(READ ${file} text)
set(patched "${text}")
# The run loop takes any interruption to mean "finished": it leaves the
# loop and stops the whole simulation. Go round again when the interruption
# was a reset, so that the top of the loop holds the core until release.
string(REPLACE
  "    } while(!core->get_interrupt_execution());"
  "    } while(!core->get_interrupt_execution() || rst_i.read());"
  patched "${patched}")
# A core asleep in WFI only wakes for an interrupt, so a reset has to wake
# it too. The debugger already has a way to do that.
string(REPLACE
  "    if(rst_i.read())\n        core->set_interrupt_execution(true);\n}"
  "    if(rst_i.read()) {\n        core->set_interrupt_execution(true);\n        vm->get_arch()->cancel_wait();\n    }\n}"
  patched "${patched}")
# Reset sets the core's cycle count back to zero, but the count that the
# quantum keeper measures progress from kept its old value. The difference
# then came out as an enormous number of cycles, and the core waited that
# long before its first instruction.
if(NOT patched MATCHES "last_sync_cycle = vm->get_arch")
  string(REPLACE
    "        quantum_keeper.reset(sc_core::sc_time_stamp());\n"
    "        quantum_keeper.reset(sc_core::sc_time_stamp());\n        last_sync_cycle = vm->get_arch()->get_instrumentation_if()->get_total_cycles();\n"
    patched "${patched}")
endif()
if(NOT patched STREQUAL text)
  file(WRITE ${file} "${patched}")
endif()
