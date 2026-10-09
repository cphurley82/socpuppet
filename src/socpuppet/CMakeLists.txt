# core/: plain C++ with no simulator underneath. Linking only this target is
# what keeps SystemC out of the kernel-free unit tests.
#
# Listing the headers as a file set puts src/ on the include path of
# whatever links the library, and lets `check_headers` compile each one on
# its own.
add_library(socpuppet_core INTERFACE)
target_sources(socpuppet_core INTERFACE
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    core/block_store.h
    core/command_status.h
    core/interrupt_requests.h
    core/memory_port.h
    core/memory_store.h
    core/nand_array.h
    core/nand_geometry.h
    core/nand_port.h
    core/script.h
    core/time.h
    core/trace.h)

# Reading ELF files is ELFIO's work. Like the adapters below, the one source
# file that uses the borrowed library is compiled on its own.
add_library(socpuppet_elf_image STATIC core/elf_image.cpp)
target_sources(socpuppet_elf_image PUBLIC
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    core/elf_image.h)
target_link_libraries(socpuppet_elf_image PRIVATE elfio::elfio)
socpuppet_dev_checks(socpuppet_elf_image)
target_link_libraries(socpuppet_core INTERFACE socpuppet_elf_image)

# The NVMe controller's logic is ours, and the layout of every register,
# command and data structure it handles is SPDK's.
add_library(socpuppet_nvme_controller STATIC core/nvme_controller.cpp)
target_sources(socpuppet_nvme_controller PUBLIC
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    core/nvme_controller.h
    core/prp.h)
target_link_libraries(socpuppet_nvme_controller PRIVATE spdk_nvme_spec)
socpuppet_dev_checks(socpuppet_nvme_controller)
target_link_libraries(socpuppet_core INTERFACE socpuppet_nvme_controller)

# The devices of the SSD that are neither its CPU nor its NVMe frontend:
# the flash controller, in front of the NAND.
add_library(socpuppet_ssd_devices STATIC
  core/dma_engine_logic.cpp
  core/flash_controller_logic.cpp)
target_sources(socpuppet_ssd_devices PUBLIC
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    core/dma_engine_logic.h
    core/flash_controller_logic.h)
socpuppet_dev_checks(socpuppet_ssd_devices)
target_link_libraries(socpuppet_core INTERFACE socpuppet_ssd_devices)

# What a PCIe endpoint's registers do. Ours, and long enough to be worth
# compiling once.
add_library(socpuppet_pcie_registers STATIC
  core/msix_table.cpp
  core/pcie_endpoint_registers.cpp)
target_sources(socpuppet_pcie_registers PUBLIC
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    core/little_endian.h
    core/msix_table.h
    core/pcie_endpoint_registers.h)
socpuppet_dev_checks(socpuppet_pcie_registers)
target_link_libraries(socpuppet_core INTERFACE socpuppet_pcie_registers)

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

# The machine timer: VPV-Peripherals' ACLINT. The model has a source file of
# its own, which is built as a library apart from ours so that our warnings
# and clang-tidy leave it alone. SC_SIGNAL_IF asks the model for plain
# SystemC signals as its interrupt outputs.
add_library(vpv_aclint STATIC ${vpv_peripherals_SOURCE_DIR}/minres/aclint.cpp)
target_compile_definitions(vpv_aclint PUBLIC SC_SIGNAL_IF)
target_compile_options(vpv_aclint PRIVATE -w)
target_include_directories(vpv_aclint SYSTEM PUBLIC
  ${vpv_peripherals_SOURCE_DIR})
target_link_libraries(vpv_aclint PUBLIC scc::components SystemC::systemc)

add_library(socpuppet_machine_timer STATIC models/machine_timer.cpp)
target_sources(socpuppet_machine_timer PUBLIC
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    models/machine_timer.h)
target_link_libraries(socpuppet_machine_timer
  PUBLIC SystemC::systemc
  PRIVATE vpv_aclint)
socpuppet_dev_checks(socpuppet_machine_timer)

# The interrupt controller: VPV-Peripherals' PLIC, which is headers only.
# SC_SIGNAL_IF is private here where the timer's is public: plic.cpp is the
# only file that sees the borrowed header, so nothing else has to agree.
add_library(socpuppet_plic STATIC models/plic.cpp)
target_sources(socpuppet_plic PUBLIC
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    models/plic.h)
target_compile_definitions(socpuppet_plic PRIVATE SC_SIGNAL_IF)
target_link_libraries(socpuppet_plic
  PUBLIC SystemC::systemc
  PRIVATE scc::components)
target_include_directories(socpuppet_plic SYSTEM PRIVATE
  ${vpv_peripherals_SOURCE_DIR})
socpuppet_dev_checks(socpuppet_plic)

# platform/: composing components by name (ports, the registry, the
# platform builder), and what a model needs from the platform to take part.
add_library(socpuppet_platform STATIC platform/platform.cpp)
target_sources(socpuppet_platform PUBLIC
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    platform/errors.h
    platform/failure.h
    platform/logging.h
    platform/platform.h
    platform/port.h
    platform/registry.h
    platform/slots.h
    platform/time_conversion.h
    platform/tracer.h
    platform/transport.h)
target_link_libraries(socpuppet_platform PUBLIC
  socpuppet_core scc::components SystemC::systemc)
socpuppet_dev_checks(socpuppet_platform)

# models/: the SystemC wrappers. Header-only, apart from the adapters above.
add_library(socpuppet_models INTERFACE)
target_sources(socpuppet_models INTERFACE
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    models/behavioral_nvme.h
    models/command_device.h
    models/flash_controller.h
    models/ideal_nand.h
    models/interrupt_lines.h
    models/memory.h
    models/msi_plic_bridge.h
    models/msi_receiver.h
    models/nand_link.h
    models/pass_through_link.h
    models/pcie_endpoint.h
    models/pcie_link.h
    models/pcie_root_complex.h
    models/scripted_bus_master.h
    models/socket_memory.h
    models/tie_low.h)
target_link_libraries(socpuppet_models INTERFACE
  socpuppet_platform socpuppet_dbt_rise_cpu socpuppet_machine_timer
  socpuppet_ns16550 socpuppet_plic)

# The registry of everything above, by name. Compiled on its own, so that a
# file that only wants the registry does not compile every model to get it.
add_library(socpuppet_builtin_components STATIC models/builtin_components.cpp)
target_sources(socpuppet_builtin_components PUBLIC
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    models/builtin_components.h)
target_link_libraries(socpuppet_builtin_components
  PUBLIC socpuppet_platform
  PRIVATE socpuppet_models)
socpuppet_dev_checks(socpuppet_builtin_components)

socpuppet_check_headers(
  socpuppet_core socpuppet_elf_image socpuppet_nvme_controller
  socpuppet_ssd_devices socpuppet_pcie_registers socpuppet_platform socpuppet_models socpuppet_builtin_components
  socpuppet_dbt_rise_cpu socpuppet_machine_timer socpuppet_ns16550
  socpuppet_plic)

# What the extension below is made of, besides its one source file. Listed
# as a library of their own so that `check_headers` compiles each alone.
add_library(socpuppet_bindings INTERFACE)
target_sources(socpuppet_bindings INTERFACE
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    bindings/python_executor.h
    bindings/python_script.h)
target_link_libraries(socpuppet_bindings INTERFACE
  socpuppet_models pybind11::module)
socpuppet_check_headers(socpuppet_bindings)

# The Python extension. It is the one binary in a Python process that embeds
# the SystemC kernel.
pybind11_add_module(_core bindings/core.cpp)
target_link_libraries(_core PRIVATE
  socpuppet_bindings socpuppet_builtin_components socpuppet_models)
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
