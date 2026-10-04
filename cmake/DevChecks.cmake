# Checks applied to our own code while it is built.

option(SOCPUPPET_DEVELOPER_MODE
  "Hold our own code to the project's standards while building it" OFF)

find_package(Python REQUIRED COMPONENTS Interpreter)
set(_socpuppet_lint ${CMAKE_CURRENT_LIST_DIR}/../tools/lint.py)

if(SOCPUPPET_DEVELOPER_MODE)
  # Formats the project's C++ and Python in place. Our targets depend on it,
  # so it has finished before anything is compiled. (The plain name "format"
  # is taken: yaml-cpp defines a target called that.)
  add_custom_target(socpuppet_format
    COMMAND ${Python_EXECUTABLE} ${_socpuppet_lint}
            --fix clang-format ruff-format
    WORKING_DIRECTORY ${PROJECT_SOURCE_DIR}
    COMMENT "Formatting C++ and Python"
    VERBATIM)
endif()

# Applies the checks to the targets named, which must be ours: never call
# this on a dependency.
function(socpuppet_dev_checks)
  foreach(target IN LISTS ARGN)
    if(SOCPUPPET_DEVELOPER_MODE)
      target_compile_options(${target} PRIVATE
        -Wall
        -Wextra
        -Wpedantic         # anything the C++ standard does not allow
        -Wshadow           # a name that hides another
        -Wconversion       # a conversion that can lose part of the value
        -Wsign-conversion  # a conversion that can change the sign
      )
      set_target_properties(${target} PROPERTIES COMPILE_WARNING_AS_ERROR ON)
      add_dependencies(${target} socpuppet_format)
    endif()
  endforeach()
endfunction()
