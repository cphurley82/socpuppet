# Checks applied to our own code while it is built.

option(SOCPUPPET_DEVELOPER_MODE
  "Hold our own code to the project's standards while building it" OFF)

# Applies the checks to the targets named, which must be ours: never call
# this on a dependency.
function(socpuppet_dev_checks)
  foreach(target IN LISTS ARGN)
    if(SOCPUPPET_DEVELOPER_MODE)
      target_compile_options(${target} PRIVATE -Wall)
      set_target_properties(${target} PROPERTIES COMPILE_WARNING_AS_ERROR ON)
    endif()
  endforeach()
endfunction()
