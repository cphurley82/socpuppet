# The PCIe spike (milestone M2): can VCML's PCI model be socpuppet's PCIe
# endpoint? Exploratory code with a build of its own, in build/spike-pcie.
# It is not part of socpuppet and nothing outside spikes/ may depend on it.
# See README.md here and docs/pcie-spike.md.
cmake_minimum_required(VERSION 3.28)
project(socpuppet_pcie_spike LANGUAGES CXX C)

# The same settings as the top-level CMakeLists.txt, for the same reasons.
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(BUILD_SHARED_LIBS OFF)
set(SOCPUPPET_BUILD_TESTS ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

get_filename_component(SOCPUPPET_ROOT ${CMAKE_CURRENT_LIST_DIR}/../.. ABSOLUTE)

# The main build has already downloaded and patched every dependency. Use
# its copies where they are, read-only, and fetch only what is missing.
set(SPIKE_REUSE_DEPS ${SOCPUPPET_ROOT}/build/dev/_deps CACHE PATH
  "A _deps directory whose fetched sources this build may read")
foreach(dep systemc googletest pybind11 Boost fmt spdlog yaml-cpp scc elfio
            dbt_rise_riscv dbt_rise_core_git vpv_peripherals)
  string(TOLOWER ${dep} _lower)
  string(TOUPPER ${dep} _upper)
  if(EXISTS ${SPIKE_REUSE_DEPS}/${_lower}-src)
    set(FETCHCONTENT_SOURCE_DIR_${_upper} ${SPIKE_REUSE_DEPS}/${_lower}-src)
  endif()
endforeach()
if(EXISTS ${SPIKE_REUSE_DEPS}/spdk_nvme_spec-src/spdk)
  set(FETCHCONTENT_SOURCE_DIR_SPDK_NVME_SPEC
    ${SPIKE_REUSE_DEPS}/spdk_nvme_spec-src/spdk)
endif()

include(${SOCPUPPET_ROOT}/cmake/Dependencies.cmake)
include(${SOCPUPPET_ROOT}/cmake/DevChecks.cmake)

# socpuppet's own libraries, built here from the working tree. Its
# CMakeLists.txt finds its sources through PROJECT_SOURCE_DIR.
set(_spike_source_dir ${PROJECT_SOURCE_DIR})
set(PROJECT_SOURCE_DIR ${SOCPUPPET_ROOT})
add_subdirectory(${SOCPUPPET_ROOT}/src/socpuppet socpuppet EXCLUDE_FROM_ALL)
set(PROJECT_SOURCE_DIR ${_spike_source_dir})
# That file puts the extension into the source tree, where the main build's
# own copy lives. This build's copy stays in this build's directory.
set(SPIKE_PYTHON_DIR ${CMAKE_BINARY_DIR}/python)
set_target_properties(_core PROPERTIES
  LIBRARY_OUTPUT_DIRECTORY ${SPIKE_PYTHON_DIR})

# ---- VCML ------------------------------------------------------------------
set(SPIKE_MWR_PIN target CACHE STRING "How mwr is pinned (see pin_probe/)")
include(Vcml.cmake)
set(SOCPUPPET_SUPPRESS_INSTALL TRUE)
spike_fetch_vcml()
set(SOCPUPPET_SUPPRESS_INSTALL FALSE)

# ---- The adapters -------------------------------------------------------------
# Built the way socpuppet builds an adapter around a borrowed model: a static
# library of its own, whose source files are the only ones that see the
# borrowed headers. VCML is linked PRIVATE, so what VCML asks of everything
# that compiles against it (SC_DISABLE_API_VERSION_CHECK among it) stops
# here.
add_library(spike_vcml_endpoint STATIC
  vcml_endpoint.cpp vcml_bare_endpoint.cpp)
# Headers are included by their path from the top of the repository:
# "spikes/pcie/vcml_endpoint.h".
target_include_directories(spike_vcml_endpoint PUBLIC ${SOCPUPPET_ROOT})
target_link_libraries(spike_vcml_endpoint
  PUBLIC SystemC::systemc
  PRIVATE vcml)

# The first adapter with VCML left as it comes, to show what the
# corrections are for.
add_library(spike_vcml_endpoint_as_is STATIC vcml_endpoint.cpp)
target_compile_definitions(spike_vcml_endpoint_as_is PRIVATE
  SPIKE_VCML_AS_IS)
target_include_directories(spike_vcml_endpoint_as_is PUBLIC ${SOCPUPPET_ROOT})
target_link_libraries(spike_vcml_endpoint_as_is
  PUBLIC SystemC::systemc
  PRIVATE vcml)

# ---- The tests ----------------------------------------------------------------
# Each starts the SystemC kernel, which cannot be restarted, so CTest runs
# each in a process of its own.
include(GoogleTest)
enable_testing()
function(spike_test_program name adapter)
  add_executable(${name}
    ${SOCPUPPET_ROOT}/tests/cpp/kernel_test_main.cpp
    ${ARGN})
  target_link_libraries(${name} PRIVATE
    ${adapter} socpuppet_models scc::components GTest::gmock)
  # The program's name goes in front, so that CTest can tell the same test
  # in two programs apart.
  gtest_discover_tests(${name} TEST_PREFIX ${name}.)
endfunction()

spike_test_program(spike_pcie_tests spike_vcml_endpoint endpoint_test.cpp)
spike_test_program(spike_vcml_as_is_tests spike_vcml_endpoint_as_is
  as_is_test.cpp)
# The same tests on the adapter that borrows the endpoint without the host.
spike_test_program(spike_pcie_bare_tests spike_vcml_endpoint
  endpoint_test.cpp)
target_compile_definitions(spike_pcie_bare_tests PRIVATE SPIKE_BARE_ENDPOINT)

# ---- The Python extension, with VCML inside ---------------------------------
# A copy of socpuppet's extension under another name, _core_vcml, whose
# platforms can also be built with a "vcml_pcie_endpoint". The copy is made
# from the working tree's bindings/core.cpp each time CMake configures.
file(READ ${SOCPUPPET_ROOT}/src/socpuppet/bindings/core.cpp _core_source)
string(REPLACE "PYBIND11_MODULE(_core, m)" "PYBIND11_MODULE(_core_vcml, m)"
  _core_source "${_core_source}")
string(REPLACE "platform{socpuppet::BuiltinComponents()}"
  "platform{spike::WithVcmlEndpoint()}" _core_source "${_core_source}")
set(_core_vcml_source ${CMAKE_BINARY_DIR}/generated/core_vcml.cpp)
file(CONFIGURE OUTPUT ${_core_vcml_source} @ONLY CONTENT
  "#include \"spikes/pcie/components.h\"\n${_core_source}")
file(STRINGS ${_core_vcml_source} _renamed REGEX "_core_vcml|WithVcmlEndpoint")
list(LENGTH _renamed _renamed_lines)
if(NOT _renamed_lines EQUAL 2)
  message(FATAL_ERROR "bindings/core.cpp has changed shape: the spike's two "
    "replacements in it no longer both apply. See spikes/pcie/CMakeLists.txt.")
endif()

set(SPIKE_PYTHON_VCML_DIR ${CMAKE_BINARY_DIR}/python-vcml)
pybind11_add_module(_core_vcml ${_core_vcml_source})
target_link_libraries(_core_vcml PRIVATE socpuppet_models spike_vcml_endpoint)
set_target_properties(_core_vcml PROPERTIES
  LIBRARY_OUTPUT_DIRECTORY ${SPIKE_PYTHON_VCML_DIR})

# A `socpuppet` package to go with it: the working tree's Python sources,
# linked to, and a `_core` that hands on everything in _core_vcml. With
# this directory first on PYTHONPATH, socpuppet's own Python runs on the
# extension that has VCML in it.
file(MAKE_DIRECTORY ${SPIKE_PYTHON_VCML_DIR}/socpuppet)
file(GLOB _python_sources RELATIVE ${SOCPUPPET_ROOT}/python/socpuppet
  ${SOCPUPPET_ROOT}/python/socpuppet/*)
foreach(entry ${_python_sources})
  if(NOT entry MATCHES "^_core|__pycache__")
    file(CREATE_LINK ${SOCPUPPET_ROOT}/python/socpuppet/${entry}
      ${SPIKE_PYTHON_VCML_DIR}/socpuppet/${entry} SYMBOLIC)
  endif()
endforeach()
# With SPIKE_IMPORT_LOG set, each process that imports it adds a line to
# that file: the proof that a test run really was on this extension.
file(WRITE ${SPIKE_PYTHON_VCML_DIR}/socpuppet/_core.py
"import os

from _core_vcml import *  # noqa: F403

if log := os.environ.get(\"SPIKE_IMPORT_LOG\"):
    with open(log, \"a\") as out:
        out.write(f\"{os.getpid()}\\n\")
")
