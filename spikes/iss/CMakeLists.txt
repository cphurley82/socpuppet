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
# Built by its own CMakeLists, as an interpreter only: the TinyCC backend is
# LGPL, and the asmjit and LLVM backends would each be one more dependency.
include(FetchContent)
FetchContent_Declare(elfio
  URL https://github.com/serge1/ELFIO/archive/refs/tags/Release_3.12.tar.gz
  URL_HASH SHA256=e4ebc9ce3d6916461bc3e7765bb45e6210f0a9b93978bf91e59b05388c024489
  EXCLUDE_FROM_ALL SYSTEM)
set(WITH_TCC OFF)
set(WITH_ASMJIT OFF)
set(WITH_LLVM OFF)
set(DBT_RISE_RISCV_ENABLE_VECTOR OFF)
set(UPDATE_EXTERNAL_PROJECT OFF)
FetchContent_Declare(dbt_rise_riscv
  GIT_REPOSITORY https://github.com/Minres/DBT-RISE-RISCV.git
  GIT_TAG 2ad322399bc367db6b45f76ec3d7150d8dadeae6 # 2026-09-24
  GIT_SUBMODULES softvector
  PATCH_COMMAND ${CMAKE_COMMAND} -P
                ${CMAKE_CURRENT_LIST_DIR}/patches/dbt_rise_riscv.cmake
  UPDATE_DISCONNECTED TRUE
  EXCLUDE_FROM_ALL SYSTEM)
# DBT-RISE-RISCV fetches its core library itself, under this name and at
# this commit. Declaring it here first is how the patch gets applied.
FetchContent_Declare(dbt_rise_core_git
  GIT_REPOSITORY https://github.com/Minres/DBT-RISE-Core.git
  GIT_TAG 29e97c021c988370f5c5af5b5076afe8043402b6
  PATCH_COMMAND ${CMAKE_COMMAND} -P
                ${CMAKE_CURRENT_LIST_DIR}/patches/dbt_rise_core.cmake
  UPDATE_DISCONNECTED TRUE
  EXCLUDE_FROM_ALL SYSTEM)
set(SOCPUPPET_SUPPRESS_INSTALL TRUE)
FetchContent_MakeAvailable(elfio dbt_rise_riscv)
set(SOCPUPPET_SUPPRESS_INSTALL FALSE)

# What it took to build it here. Each of these is a finding for the report.
#
# 1. A system-wide Boost keeps every header in one directory, and
#    DBT-RISE relies on that. The fetched Boost has one target per library,
#    so each library whose headers are used has to be named. DBT-RISE-RISCV
#    passes on the core library's include path as it stood when it was
#    configured, so it has to be told as well.
set(_dbt_rise_boost
  Boost::asio Boost::bind Boost::coroutine2 Boost::foreach Boost::fusion
  Boost::lexical_cast Boost::optional Boost::phoenix Boost::serialization
  Boost::smart_ptr Boost::spirit Boost::thread Boost::tokenizer Boost::tuple
  Boost::variant)
target_link_libraries(dbt-rise-core PUBLIC ${_dbt_rise_boost})
target_link_libraries(dbt-rise-riscv PUBLIC ${_dbt_rise_boost})
# 2. macOS: a helper for the JIT backends declares a C function called
#    wait(), which is already taken by POSIX. No JIT backend is built, so
#    the file is left out.
get_target_property(_core_sources dbt-rise-core SOURCES)
list(REMOVE_ITEM _core_sources src/iss/vm_jit_funcs.cpp)
set_target_properties(dbt-rise-core PROPERTIES SOURCES "${_core_sources}")
# 3. Clang: the vector helpers specialize std::make_signed for 128-bit
#    integers, which the standard forbids and Clang treats as an error.
target_compile_options(softvector PUBLIC
  $<$<CXX_COMPILER_ID:AppleClang,Clang>:-Wno-invalid-specialization>)

spike_test_program(spike_dbt_rise_tests dbt_rise/dbt_rise_test.cpp)
# 4. The cores register themselves with a factory from a static
#    initializer that nothing refers to, so a linker picking what it needs
#    out of the library leaves them all behind. The whole library has to
#    be linked in.
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
