# Checks applied to our own code while it is built.

option(SOCPUPPET_DEVELOPER_MODE
  "Hold our own code to the project's standards while building it" OFF)

find_package(Python REQUIRED COMPONENTS Interpreter)
set(_socpuppet_lint ${CMAKE_CURRENT_LIST_DIR}/../tools/lint.py)

# CI sets this variable. There, a misformatted file should fail the lint
# check, not be quietly repaired in a checkout that is then thrown away.
if(SOCPUPPET_DEVELOPER_MODE AND NOT DEFINED ENV{CI})
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

# The developer tools are installed next to the interpreter (pyproject.toml).
get_filename_component(_socpuppet_tools ${Python_EXECUTABLE} DIRECTORY)

# clang-tidy reads how each source is compiled from compile_commands.json.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Apple's compiler knows where its SDK is without being told, so the compile
# commands do not say. clang-tidy is not Apple's and has to be told, or it
# cannot find even the standard library.
set(_socpuppet_tidy_sdk)
if(APPLE)
  execute_process(COMMAND xcrun --show-sdk-path
    OUTPUT_VARIABLE sdk OUTPUT_STRIP_TRAILING_WHITESPACE COMMAND_ERROR_IS_FATAL ANY)
  set(_socpuppet_tidy_sdk -extra-arg=-isysroot${sdk})
endif()

if(SOCPUPPET_DEVELOPER_MODE)
  # Runs clang-tidy, several files at a time, over the sources of our
  # targets and the headers of ours that they include. It is a target to ask
  # for, not part of every build, because it takes far longer than compiling.
  add_custom_target(tidy
    COMMAND ${Python_EXECUTABLE} ${_socpuppet_tools}/run-clang-tidy.py
            -quiet
            -clang-tidy-binary ${_socpuppet_tools}/clang-tidy
            -p ${CMAKE_BINARY_DIR}
            ${_socpuppet_tidy_sdk}
            # The compile commands are the real compiler's, and may carry
            # warning flags that only GCC knows.
            -extra-arg=-Wno-unknown-warning-option
            "$<TARGET_PROPERTY:tidy,SOCPUPPET_SOURCES>"
    WORKING_DIRECTORY ${PROJECT_SOURCE_DIR}
    COMMENT "Running clang-tidy"
    COMMAND_EXPAND_LISTS
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
    endif()
    if(TARGET tidy)
      get_target_property(sources ${target} SOURCES)
      get_target_property(directory ${target} SOURCE_DIR)
      list(TRANSFORM sources PREPEND ${directory}/)
      set_property(TARGET tidy APPEND PROPERTY SOCPUPPET_SOURCES ${sources})
    endif()
    if(TARGET socpuppet_format)
      add_dependencies(${target} socpuppet_format)
    endif()
  endforeach()
endfunction()

if(SOCPUPPET_DEVELOPER_MODE)
  # Compiles each header of our header-only libraries on its own, which
  # shows that it includes everything it uses. A target to ask for.
  add_custom_target(check_headers)
endif()

# Has `check_headers` cover the header-only libraries named. Their headers
# must be listed in a FILE_SET HEADERS.
function(socpuppet_check_headers)
  if(NOT TARGET check_headers)
    return()
  endif()
  foreach(library IN LISTS ARGN)
    set_target_properties(${library} PROPERTIES VERIFY_INTERFACE_HEADER_SETS ON)
    # CMake names the target that does the compiling after the library.
    add_dependencies(check_headers ${library}_verify_interface_header_sets)
  endforeach()
endfunction()
