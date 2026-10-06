# How the spike brings VCML (MachineWare, Apache-2.0) into a build, in one
# place so that the probe and the real spike do exactly the same thing.
include(FetchContent)

# Release v2026.10.02 of both. mwr tags its releases with the same names as
# VCML, and VCML's own build would take the head of mwr's default branch.
set(SPIKE_VCML_COMMIT 1ef00c57a6f455864ed300087f6708c75ca13e00)
set(SPIKE_MWR_COMMIT 04bb31fc20ac79333909aa11b271b7888b2ea5e7)
set(SPIKE_MWR_TAG v2026.10.02)

function(spike_fetch_vcml)
  # Everything optional that would reach for the machine: graphics,
  # networking, scripting, CAN and USB.
  foreach(extra SDL2 SLIRP TAP LUA SOCKETCAN USB)
    set(VCML_USE_${extra} OFF)
  endforeach()
  set(VCML_BUILD_TESTS OFF)
  set(VCML_BUILD_UTILS OFF)
  # Keeps mwr off the machine's libelf. A cache entry, because mwr declares
  # its options with set(CACHE), which discards an ordinary variable of the
  # same name.
  set(MWR_USE_LIBELF OFF CACHE BOOL "Keep mwr off the machine's libelf" FORCE)

  if(SPIKE_MWR_PIN STREQUAL "target" OR SPIKE_MWR_PIN STREQUAL "home")
    FetchContent_Declare(mwr
      GIT_REPOSITORY https://github.com/machineware-gmbh/mwr.git
      GIT_TAG ${SPIKE_MWR_COMMIT} # ${SPIKE_MWR_TAG}
      GIT_SUBMODULES cmake
      EXCLUDE_FROM_ALL SYSTEM)
    if(SPIKE_MWR_PIN STREQUAL "target")
      # VCML's find_github_repo() does nothing when the target exists.
      FetchContent_MakeAvailable(mwr)
    else()
      # Fetched but not added: VCML adds it, from where MWR_HOME says.
      FetchContent_Populate(mwr)
      set(MWR_HOME ${mwr_SOURCE_DIR})
    endif()
  elseif(SPIKE_MWR_PIN STREQUAL "tag")
    set(MWR_TAG ${SPIKE_MWR_TAG} CACHE STRING "mwr repository tag/branch")
  endif()

  FetchContent_Declare(vcml
    GIT_REPOSITORY https://github.com/machineware-gmbh/vcml.git
    GIT_TAG ${SPIKE_VCML_COMMIT} # v2026.10.02
    GIT_SUBMODULES cmake
    EXCLUDE_FROM_ALL SYSTEM)
  FetchContent_MakeAvailable(vcml)
endfunction()
