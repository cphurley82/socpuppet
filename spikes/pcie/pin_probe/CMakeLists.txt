# Question 1 of the PCIe spike, on its own so that it configures in seconds:
# can VCML's support library, mwr, be pinned from outside? Nothing here is
# built for use. See ../README.md.
#
#   -DSPIKE_MWR_PIN=target   declare mwr ourselves, before VCML looks for it
#   -DSPIKE_MWR_PIN=home     hand VCML a checkout through MWR_HOME
#   -DSPIKE_MWR_PIN=tag      let VCML clone it, at a tag, through MWR_TAG
#   -DSPIKE_MWR_PIN=none     what VCML does when left alone
cmake_minimum_required(VERSION 3.28)
project(socpuppet_pcie_pin_probe LANGUAGES CXX C)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(SPIKE_MWR_PIN target CACHE STRING "How mwr is pinned")
include(${CMAKE_CURRENT_LIST_DIR}/../Vcml.cmake)

include(FetchContent)
FetchContent_Declare(systemc
  URL https://github.com/accellera-official/systemc/archive/refs/tags/3.0.2.tar.gz
  URL_HASH SHA256=9b3693ed286aab958b9e5d79bb0ad3bc523bbc46931100553275352038f4a0c4
  EXCLUDE_FROM_ALL SYSTEM)
FetchContent_MakeAvailable(systemc)
spike_fetch_vcml()

# The commit of mwr that this configure ended up with.
get_target_property(_mwr_dir mwr SOURCE_DIR)
execute_process(COMMAND git -C ${_mwr_dir} rev-parse HEAD
  OUTPUT_VARIABLE _mwr_commit OUTPUT_STRIP_TRAILING_WHITESPACE)
message(NOTICE "pin_probe: SPIKE_MWR_PIN=${SPIKE_MWR_PIN} gave mwr "
  "${_mwr_commit} from ${_mwr_dir}")
