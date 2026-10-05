# The ISS spike (milestone M1): exploratory code that compares CPU models
# behind a draft CPU slot. It is not part of socpuppet, nothing under src/,
# python/ or tests/ may depend on it, and it goes away when M3 builds the
# real CPU kit. See README.md here and docs/iss-spike.md.
include(GoogleTest)

# One test program per candidate, so that two candidates' symbols never
# meet in one link. Every test carries the label `spike`.
function(spike_test_program name)
  add_executable(${name}
    ${PROJECT_SOURCE_DIR}/tests/cpp/kernel_test_main.cpp
    ${ARGN})
  target_link_libraries(${name} PRIVATE
    socpuppet_models scc::components GTest::gmock)
  # Headers are included by their path from the top of the repository:
  # "spikes/iss/cpu_slot.h".
  target_include_directories(${name} PRIVATE ${PROJECT_SOURCE_DIR})
  # Where firmware/build.sh leaves the images the candidates boot.
  target_compile_definitions(${name} PRIVATE
    SPIKE_FIRMWARE_DIR="${PROJECT_SOURCE_DIR}/build/firmware")
  socpuppet_dev_checks(${name})
  gtest_discover_tests(${name} PROPERTIES LABELS spike)
endfunction()

spike_test_program(spike_harness_tests harness/harness_test.cpp)

# ---- DBT-RISE-RISCV (Minres, BSD-3-Clause) ---------------------------------
# The chosen CPU. It is fetched, patched and built in
# cmake/Dependencies.cmake now, for the real CPU model. What is left here
# is the spike's own wrapper around it, which goes when M3a is done.
spike_test_program(spike_dbt_rise_tests dbt_rise/dbt_rise_test.cpp)
# The cores register themselves with a factory from a static initializer
# that nothing refers to, so the whole library has to be linked in.
target_link_libraries(spike_dbt_rise_tests PRIVATE
  $<LINK_LIBRARY:WHOLE_ARCHIVE,dbt-rise-riscv_sc_sig>)

# ---- riscv-vp (University of Bremen, MIT) -----------------------------------
# Only its ISS core is used, compiled here from its sources. Its own build
# brings a whole virtual platform with it, and a SystemC of its own.
#
# This is the original, not the riscv-vp-plusplus fork: the fork's faster
# core builds its dispatch table out of ELF linker sections and does not
# compile on macOS (see docs/iss-spike.md).
FetchContent_Declare(riscv_vp
  GIT_REPOSITORY https://github.com/agra-uni-bremen/riscv-vp.git
  GIT_TAG 48b2f5877b2368cc466fb0da155db349e676c0b0 # 2024-12-13
  GIT_SUBMODULES ""
  PATCH_COMMAND ${CMAKE_COMMAND} -P
                ${CMAKE_CURRENT_LIST_DIR}/patches/riscv_vp.cmake
  UPDATE_DISCONNECTED TRUE
  EXCLUDE_FROM_ALL SYSTEM)
FetchContent_MakeAvailable(riscv_vp)
set(_riscv_vp ${riscv_vp_SOURCE_DIR}/vp/src)

# Its copy of Berkeley SoftFloat, under a name of our own: DBT-RISE-RISCV
# has a target called `softfloat` too.
file(GLOB _riscv_vp_softfloat_sources ${_riscv_vp}/vendor/softfloat/*.c)
add_library(riscv_vp_softfloat STATIC ${_riscv_vp_softfloat_sources})
target_compile_definitions(riscv_vp_softfloat PRIVATE
  SOFTFLOAT_ROUND_ODD INLINE_LEVEL=5 SOFTFLOAT_FAST_DIV32TO16
  SOFTFLOAT_FAST_DIV64TO32 SOFTFLOAT_FAST_INT64)
target_include_directories(riscv_vp_softfloat PRIVATE
  ${_riscv_vp}/vendor/softfloat/include/softfloat)
target_include_directories(riscv_vp_softfloat SYSTEM PUBLIC
  ${_riscv_vp}/vendor/softfloat/include)
target_compile_options(riscv_vp_softfloat PRIVATE -w)

add_library(riscv_vp_core STATIC
  ${_riscv_vp}/core/common/instr.cpp
  ${_riscv_vp}/core/rv32/iss.cpp
  ${_riscv_vp}/core/rv64/iss.cpp)
target_include_directories(riscv_vp_core SYSTEM PUBLIC
  ${_riscv_vp} ${_riscv_vp}/core/common)
target_link_libraries(riscv_vp_core PUBLIC
  SystemC::systemc riscv_vp_softfloat
  Boost::format Boost::io Boost::lexical_cast)
target_compile_options(riscv_vp_core PRIVATE -w)
# It was written for SystemC 2.3 and uses SC_HAS_PROCESS, which SystemC 3.0
# only offers on request.
target_compile_definitions(riscv_vp_core PUBLIC SC_ALLOW_DEPRECATED_IEEE_API)

spike_test_program(spike_riscv_vp_tests riscv_vp/riscv_vp_test.cpp)
target_link_libraries(spike_riscv_vp_tests PRIVATE riscv_vp_core)

# ---- The in-house prototype -------------------------------------------------
spike_test_program(spike_inhouse_tests inhouse/inhouse_test.cpp)
