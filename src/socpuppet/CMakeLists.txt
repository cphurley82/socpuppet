# The register maps of our own blocks, as C. tools/regs.py writes each
# header from a SystemRDL file in regs/, and they are kept where a Zephyr
# build finds them as well, because the drivers include the same files:
# the model and its driver cannot then disagree about a register.
set(_socpuppet_regs ${PROJECT_SOURCE_DIR}/python/socpuppet/zephyr_module/include)
add_library(socpuppet_regs INTERFACE)
target_sources(socpuppet_regs INTERFACE
  FILE_SET HEADERS BASE_DIRS ${_socpuppet_regs} FILES
    ${_socpuppet_regs}/socpuppet/regs/boot_image_header.h
    ${_socpuppet_regs}/socpuppet/regs/command_device.h
    ${_socpuppet_regs}/socpuppet/regs/dma_engine.h
    ${_socpuppet_regs}/socpuppet/regs/flash_controller.h
    ${_socpuppet_regs}/socpuppet/regs/i2c_controller.h
    ${_socpuppet_regs}/socpuppet/regs/nvme_frontend.h
    ${_socpuppet_regs}/socpuppet/regs/rtc.h
    ${_socpuppet_regs}/socpuppet/regs/system_controller.h
    ${_socpuppet_regs}/socpuppet/regs/ucie_link.h
    ${_socpuppet_regs}/socpuppet/regs/virtio_mmio.h)

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
    core/i2c_device.h
    core/interrupt_file.h
    core/interrupt_requests.h
    core/link_channel.h
    core/memory_port.h
    core/memory_store.h
    core/nand_array.h
    core/nand_geometry.h
    core/nand_port.h
    core/pciem_device.h
    core/pciem_host_logic.h
    core/script.h
    core/pin_listener.h
    core/spi_device.h
    core/system_controller_logic.h
    core/time.h
    core/trace.h
    core/virtio_9p_logic.h
    core/virtio_blk_logic.h
    core/virtio_console_logic.h
    core/virtio_device.h
    core/virtio_fs_logic.h
    core/virtio_mmio_logic.h
    core/virtio_net_logic.h
    core/virtio_rng_logic.h
    core/virtqueue.h)
target_link_libraries(socpuppet_core INTERFACE socpuppet_regs)

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
add_library(socpuppet_nvme_controller STATIC
  core/nvme_controller.cpp
  core/nvme_frontend_logic.cpp
  core/nvme_host_registers.cpp
  core/nvme_queues.cpp)
target_sources(socpuppet_nvme_controller PUBLIC
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    core/nvme_controller.h
    core/nvme_frontend_logic.h
    core/nvme_host_registers.h
    core/nvme_queues.h
    core/prp.h)
target_link_libraries(socpuppet_nvme_controller
  PRIVATE socpuppet_regs spdk_nvme_spec)
socpuppet_dev_checks(socpuppet_nvme_controller)
target_link_libraries(socpuppet_core INTERFACE socpuppet_nvme_controller)

# The devices of the SSD that its CPU gives commands to: the DMA engine,
# between the host's memory and the SSD's own, and the flash controller, in
# front of the NAND.
add_library(socpuppet_ssd_devices STATIC
  core/dma_engine_logic.cpp
  core/flash_controller_logic.cpp)
target_sources(socpuppet_ssd_devices PUBLIC
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    core/dma_engine_logic.h
    core/flash_controller_logic.h)
target_link_libraries(socpuppet_ssd_devices PUBLIC socpuppet_regs)
socpuppet_dev_checks(socpuppet_ssd_devices)
target_link_libraries(socpuppet_core INTERFACE socpuppet_ssd_devices)

# What an I2C controller does: its registers, and the commands it carries
# out on its bus.
add_library(socpuppet_i2c_controller_logic STATIC
  core/i2c_controller_logic.cpp)
target_sources(socpuppet_i2c_controller_logic PUBLIC
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    core/i2c_controller_logic.h)
target_link_libraries(socpuppet_i2c_controller_logic PUBLIC socpuppet_regs)
socpuppet_dev_checks(socpuppet_i2c_controller_logic)
target_link_libraries(socpuppet_core INTERFACE socpuppet_i2c_controller_logic)

# What a real-time clock does: its registers, and its alarm.
add_library(socpuppet_rtc_logic STATIC core/rtc_logic.cpp)
target_sources(socpuppet_rtc_logic PUBLIC
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    core/rtc_logic.h)
target_link_libraries(socpuppet_rtc_logic PUBLIC socpuppet_regs)
socpuppet_dev_checks(socpuppet_rtc_logic)
target_link_libraries(socpuppet_core INTERFACE socpuppet_rtc_logic)

# A NOR flash chip on an SPI bus, the device behind the boot flash's
# controller.
add_library(socpuppet_spi_nor_chip STATIC core/spi_nor_chip.cpp)
target_sources(socpuppet_spi_nor_chip PUBLIC
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    core/spi_nor_chip.h)
socpuppet_dev_checks(socpuppet_spi_nor_chip)
target_link_libraries(socpuppet_core INTERFACE socpuppet_spi_nor_chip)

# The die-to-die link: where it is on its way up, and what its registers
# do. UCIe's state machine and message codes, from public sources.
add_library(socpuppet_ucie_link STATIC
  core/ucie_link_registers.cpp
  core/ucie_link_state.cpp)
target_sources(socpuppet_ucie_link PUBLIC
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    core/d2d_link_logic.h
    core/ucie_link_registers.h
    core/ucie_link_state.h
    core/ucie_sideband.h)
target_link_libraries(socpuppet_ucie_link PRIVATE socpuppet_regs)
socpuppet_dev_checks(socpuppet_ucie_link)
target_link_libraries(socpuppet_core INTERFACE socpuppet_ucie_link)

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
# The backend a "dbt_rise_cpu" runs with when nothing says
# (cmake/Dependencies.cmake).
target_compile_definitions(socpuppet_dbt_rise_cpu PRIVATE
  SOCPUPPET_DBT_RISE_DEFAULT_BACKEND="${SOCPUPPET_DBT_RISE_DEFAULT_BACKEND}")
socpuppet_dev_checks(socpuppet_dbt_rise_cpu)

# The second CPU: QBox's, which is QEMU's, in a build with QBox only. Its
# source file is the one that sees QBox's headers (socpuppet_qbox, in
# cmake/Dependencies.cmake).
if(SOCPUPPET_HAS_QBOX)
  add_library(socpuppet_qbox_cpu STATIC models/qbox_cpu.cpp)
  target_sources(socpuppet_qbox_cpu PUBLIC
    FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
      models/qbox_cpu.h)
  target_link_libraries(socpuppet_qbox_cpu
    PUBLIC SystemC::systemc
    PRIVATE socpuppet_qbox)
  socpuppet_dev_checks(socpuppet_qbox_cpu)
endif()

# The calls to /dev/pciem, for a real host, in a build with pciem only.
# pciem's header is GPL-2.0-only and needs C++23 for its <stdatomic.h>, and
# SystemC refuses to link with code built to another standard than its own,
# so the one source file that includes it is a library of its own, with no
# SystemC. Its test includes the header too (tests/cpp/CMakeLists.txt).
if(SOCPUPPET_HAS_PCIEM)
  add_library(socpuppet_pciem_device STATIC core/pciem_device.cpp)
  target_link_libraries(socpuppet_pciem_device PUBLIC socpuppet_core)
  target_include_directories(socpuppet_pciem_device SYSTEM PRIVATE
    ${SOCPUPPET_PCIEM_DIR})
  set_target_properties(socpuppet_pciem_device PROPERTIES CXX_STANDARD 23)
  socpuppet_dev_checks(socpuppet_pciem_device)
endif()

# One of our models, models/<name>.cpp with its header: the library
# socpuppet_<name>, linking SystemC and what PUBLIC and PRIVATE name, and
# held to our warnings and clang-tidy (cmake/DevChecks.cmake).
function(socpuppet_model name)
  cmake_parse_arguments(PARSE_ARGV 1 arg "" "" "PUBLIC;PRIVATE")
  add_library(socpuppet_${name} STATIC models/${name}.cpp)
  target_sources(socpuppet_${name} PUBLIC
    FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
      models/${name}.h)
  target_link_libraries(socpuppet_${name}
    PUBLIC SystemC::systemc ${arg_PUBLIC}
    PRIVATE ${arg_PRIVATE})
  socpuppet_dev_checks(socpuppet_${name})
endfunction()

# A model of VPV-Peripherals' with a source file of its own, `source` in its
# tree: built as a library apart from ours, so that our warnings and
# clang-tidy leave it alone.
function(socpuppet_borrowed_vpv name source)
  add_library(${name} STATIC ${vpv_peripherals_SOURCE_DIR}/${source})
  target_compile_options(${name} PRIVATE -w)
  target_include_directories(${name} SYSTEM PUBLIC
    ${vpv_peripherals_SOURCE_DIR})
  target_link_libraries(${name} PUBLIC scc::components SystemC::systemc)
endfunction()

# The UART: VPV-Peripherals' PULPino UART.
socpuppet_model(ns16550 PRIVATE scc::components)
target_include_directories(socpuppet_ns16550 SYSTEM PRIVATE
  ${vpv_peripherals_SOURCE_DIR})

# The machine timer: VPV-Peripherals' ACLINT. The model has a source file of
# its own, which is built as a library apart from ours so that our warnings
# and clang-tidy leave it alone. SC_SIGNAL_IF asks the model for plain
# SystemC signals as its interrupt outputs.
socpuppet_borrowed_vpv(vpv_aclint minres/aclint.cpp)
target_compile_definitions(vpv_aclint PUBLIC SC_SIGNAL_IF)

socpuppet_model(machine_timer PRIVATE vpv_aclint)

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

# The APLIC: VPV-Peripherals' APLIC, which has a source file of its own,
# built apart from ours as the timer's is.
socpuppet_borrowed_vpv(vpv_aplic rvi/aplic.cpp)
target_compile_definitions(vpv_aplic PUBLIC SC_SIGNAL_IF)

socpuppet_model(aplic PRIVATE vpv_aplic)

# The IOMMU: ours, written for VPV-Peripherals (src/vpvper), with an
# adapter as the borrowed models have.
socpuppet_model(iommu PRIVATE vpv_iommu)

# The watchdog: the one in VPV-Peripherals' model of SiFive's always-on
# block, built apart from ours as the timer's model is.
socpuppet_borrowed_vpv(vpv_aon sifive/aon.cpp)

socpuppet_model(watchdog PRIVATE vpv_aon)

# The GPIO: VPV-Peripherals' model of SiFive's, built apart from ours as
# the timer's model is.
socpuppet_borrowed_vpv(vpv_sifive_gpio sifive/gpio.cpp)

socpuppet_model(gpio PRIVATE vpv_sifive_gpio)

# The SPI controller: VPV-Peripherals' model of SiFive's, built apart from
# ours as the timer's model is.
socpuppet_borrowed_vpv(vpv_sifive_spi sifive/spi.cpp)

socpuppet_model(spi_controller PUBLIC socpuppet_core PRIVATE vpv_sifive_spi)

# The flash: the SPI controller above with our chip behind it.
socpuppet_model(spi_flash PUBLIC socpuppet_core socpuppet_spi_controller)

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
# With QBox's shared SystemC, every program and the extension define the
# sc_main() that SystemC's library calls and never get to
# (platform/sc_main_stub.cpp). Nothing refers to it from our side, so the
# whole library is linked.
if(SOCPUPPET_HAS_QBOX)
  add_library(socpuppet_sc_main STATIC platform/sc_main_stub.cpp)
  target_link_libraries(socpuppet_sc_main PRIVATE SystemC::systemc)
  socpuppet_dev_checks(socpuppet_sc_main)
  target_link_libraries(socpuppet_platform PUBLIC
    $<LINK_LIBRARY:WHOLE_ARCHIVE,socpuppet_sc_main>)
endif()

# models/: the SystemC wrappers. Header-only, apart from the adapters above.
add_library(socpuppet_models INTERFACE)
target_sources(socpuppet_models INTERFACE
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    models/behavioral_nvme.h
    models/command_device.h
    models/d2d_link.h
    models/dma_engine.h
    models/flash_controller.h
    models/hart_adapter.h
    models/hart_registers.h
    models/ideal_nand.h
    models/imsic.h
    models/interrupt_lines.h
    models/memory.h
    models/msi_receiver.h
    models/nand_link.h
    models/nvme_frontend.h
    models/pass_through_link.h
    models/pcie_endpoint.h
    models/pcie_link.h
    models/pcie_root_complex.h
    models/pciem_host.h
    models/rom.h
    models/rtc.h
    models/scripted_bus_master.h
    models/socket_memory.h
    models/system_controller.h
    models/tie_low.h
    models/far_end.h
    models/i2c_controller.h
    models/virtio_9p.h
    models/virtio_blk.h
    models/virtio_console.h
    models/virtio_fs.h
    models/virtio_mmio.h
    models/virtio_net.h
    models/virtio_rng.h)
target_link_libraries(socpuppet_models INTERFACE
  socpuppet_platform socpuppet_aplic socpuppet_dbt_rise_cpu socpuppet_gpio
  socpuppet_iommu socpuppet_machine_timer socpuppet_ns16550 socpuppet_plic
  socpuppet_spi_controller socpuppet_spi_flash socpuppet_watchdog
  $<$<BOOL:${SOCPUPPET_HAS_QBOX}>:socpuppet_qbox_cpu>)

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
# Whether the build has QBox's CPU and pciem (cmake/Dependencies.cmake), for
# the registry and for whatever asks it.
target_compile_definitions(socpuppet_builtin_components PUBLIC
  SOCPUPPET_HAS_QBOX=$<BOOL:${SOCPUPPET_HAS_QBOX}>
  SOCPUPPET_HAS_PCIEM=$<BOOL:${SOCPUPPET_HAS_PCIEM}>)
if(SOCPUPPET_HAS_PCIEM)
  target_link_libraries(socpuppet_builtin_components PRIVATE
    socpuppet_pciem_device)
endif()

socpuppet_check_headers(
  socpuppet_regs socpuppet_core socpuppet_elf_image socpuppet_nvme_controller
  socpuppet_ssd_devices socpuppet_ucie_link socpuppet_pcie_registers socpuppet_platform socpuppet_models socpuppet_builtin_components
  socpuppet_aplic socpuppet_dbt_rise_cpu socpuppet_gpio socpuppet_machine_timer
  socpuppet_ns16550 socpuppet_plic socpuppet_spi_controller socpuppet_spi_flash
  socpuppet_watchdog)
if(SOCPUPPET_HAS_QBOX)
  socpuppet_check_headers(socpuppet_qbox_cpu)
endif()

# What the extension below is made of, besides its one source file. Listed
# as a library of their own so that `check_headers` compiles each alone.
add_library(socpuppet_bindings INTERFACE)
target_sources(socpuppet_bindings INTERFACE
  FILE_SET HEADERS BASE_DIRS ${PROJECT_SOURCE_DIR}/src FILES
    bindings/python_executor.h
    bindings/python_i2c_device.h
    bindings/python_script.h
    bindings/python_spi_device.h)
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
  # Development: a copy of the extension next to the Python sources, so the
  # package is importable straight from the source tree. The dev and qbox
  # trees share that one place, and the last tree built must be the one
  # imported, even when it had nothing to relink.
  socpuppet_copy_into(_core ${PROJECT_SOURCE_DIR}/python/socpuppet)
endif()
