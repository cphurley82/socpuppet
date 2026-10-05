# core/: plain C++ with no simulator underneath. Linking only this target is
# what keeps SystemC out of the kernel-free unit tests.
#
# Listing the headers as a file set puts src/ on the include path of
# whatever links the library, and lets `check_headers` compile each one on
# its own.
add_library(socpuppet_core INTERFACE)
target_sources(socpuppet_core INTERFACE
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    core/memory_store.h
    core/script.h
    core/time.h
    core/trace.h)

# An adapter around a borrowed model is compiled on its own, so that its
# source file is the only one that sees the borrowed headers.
#
# The CPU: DBT-RISE-RISCV.
add_library(socpuppet_dbt_rise_cpu STATIC models/dbt_rise_cpu.cpp)
target_sources(socpuppet_dbt_rise_cpu PUBLIC
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    models/dbt_rise_cpu.h)
# DBT-RISE's cores register themselves with a factory from a static
# initializer that nothing refers to, so a linker picking what it needs out
# of the library would leave them all behind. The whole library is linked.
target_link_libraries(socpuppet_dbt_rise_cpu
  PUBLIC SystemC::systemc
  PRIVATE $<LINK_LIBRARY:WHOLE_ARCHIVE,dbt-rise-riscv_sc_sig>)
socpuppet_dev_checks(socpuppet_dbt_rise_cpu)

# The UART: VPV-Peripherals' PULPino UART.
add_library(socpuppet_ns16550 STATIC models/ns16550.cpp)
target_sources(socpuppet_ns16550 PUBLIC
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    models/ns16550.h)
target_link_libraries(socpuppet_ns16550
  PUBLIC SystemC::systemc
  PRIVATE scc::components)
target_include_directories(socpuppet_ns16550 SYSTEM PRIVATE
  ${vpv_peripherals_SOURCE_DIR})
socpuppet_dev_checks(socpuppet_ns16550)

# models/: the SystemC wrappers. platform/: composing them by name (ports,
# the registry, the platform builder). Header-only, apart from the adapters
# above.
add_library(socpuppet_models INTERFACE)
target_sources(socpuppet_models INTERFACE
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    models/builtin_components.h
    models/memory.h
    models/pass_through_link.h
    models/scripted_bus_master.h
    platform/failure.h
    platform/logging.h
    platform/platform.h
    platform/port.h
    platform/registry.h
    platform/slots.h
    platform/time_conversion.h
    platform/tracer.h)
target_link_libraries(socpuppet_models INTERFACE
  socpuppet_core socpuppet_dbt_rise_cpu socpuppet_ns16550 scc::components
  SystemC::systemc)
socpuppet_check_headers(
  socpuppet_core socpuppet_models socpuppet_dbt_rise_cpu socpuppet_ns16550)

# The Python extension. It is the one binary in a Python process that embeds
# the SystemC kernel.
pybind11_add_module(_core bindings/core.cpp)
target_link_libraries(_core PRIVATE socpuppet_models)
socpuppet_dev_checks(_core)
if(SKBUILD)
  # Building a wheel: the extension goes inside the installed package.
  install(TARGETS _core LIBRARY DESTINATION socpuppet)
else()
  # Development: emit the extension next to the Python sources so the package
  # is importable straight from the source tree.
  set_target_properties(_core PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY ${PROJECT_SOURCE_DIR}/python/socpuppet)
endif()
