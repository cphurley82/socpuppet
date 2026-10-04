# Checks applied to our own code while it is built.

option(SOCPUPPET_DEVELOPER_MODE
  "Hold our own code to the project's standards while building it" OFF)

option(SOCPUPPET_COVERAGE
  "Build our own code so that the tests record which lines they run" OFF)

option(SOCPUPPET_SANITIZE
  "Build our own programs so that memory errors and undefined behavior stop them" OFF)

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

set(SOCPUPPET_COVERAGE_CPP_FLOOR 0 CACHE STRING
  "The coverage target fails if the tests run less than this percentage of our C++ lines")
set(SOCPUPPET_COVERAGE_PYTHON_FLOOR 0 CACHE STRING
  "The coverage target fails if the tests run less than this percentage of our Python lines")

# What to run the Python tests with: `${SOCPUPPET_TEST_PYTHON} -m pytest`.
# When coverage is being measured, that is the interpreter under coverage.py.
set(SOCPUPPET_TEST_PYTHON ${Python_EXECUTABLE})
if(SOCPUPPET_COVERAGE)
  list(APPEND SOCPUPPET_TEST_PYTHON -m coverage run)
endif()

if(SOCPUPPET_COVERAGE)
  # gcov is the tool that reads the counters an instrumented program leaves
  # behind. Each compiler has its own.
  if(CMAKE_CXX_COMPILER_ID STREQUAL "AppleClang")
    set(_socpuppet_gcov "xcrun llvm-cov gcov")
  else()
    set(_socpuppet_gcov gcov)
  endif()

  # A project with Python in it gets a report on that too.
  set(_socpuppet_python_coverage_erase)
  set(_socpuppet_python_coverage_report)
  if(EXISTS ${PROJECT_SOURCE_DIR}/python)
    set(_socpuppet_coverage ${Python_EXECUTABLE} -m coverage)
    set(_socpuppet_python_coverage_erase
      COMMAND ${_socpuppet_coverage} erase)
    set(_socpuppet_python_coverage_report
      COMMAND ${_socpuppet_coverage} combine
      COMMAND ${_socpuppet_coverage} html
              --directory ${CMAKE_BINARY_DIR}/coverage/python
      COMMAND ${_socpuppet_coverage} report
              --fail-under ${SOCPUPPET_COVERAGE_PYTHON_FLOOR})
  endif()

  # Runs the tests, then reports which lines of the code under src/ and
  # python/ they ran. The reports are printed, and written as web pages to
  # coverage/cpp and coverage/python in the build directory.
  add_custom_target(coverage
    # Counters add up from one run of a program to the next, so the ones
    # left by earlier runs go first.
    COMMAND ${Python_EXECUTABLE} -c
            "import pathlib, sys; [counters.unlink() for counters in pathlib.Path(sys.argv[1]).rglob('*.gcda')]"
            ${CMAKE_BINARY_DIR}
    ${_socpuppet_python_coverage_erase}
    # The tests of the tooling itself are left out: they run none of the
    # code being measured, and they take a while.
    COMMAND ${CMAKE_CTEST_COMMAND} --test-dir ${CMAKE_BINARY_DIR}
            --output-on-failure --label-exclude tooling
    COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_BINARY_DIR}/coverage/cpp
    COMMAND ${Python_EXECUTABLE} -m gcovr
            --root ${PROJECT_SOURCE_DIR}
            --filter ${PROJECT_SOURCE_DIR}/src/
            --gcov-executable ${_socpuppet_gcov}
            --txt
            --fail-under-line ${SOCPUPPET_COVERAGE_CPP_FLOOR}
            --html-details ${CMAKE_BINARY_DIR}/coverage/cpp/index.html
            ${CMAKE_BINARY_DIR}
    ${_socpuppet_python_coverage_report}
    WORKING_DIRECTORY ${PROJECT_SOURCE_DIR}
    COMMENT "Running the tests and measuring coverage"
    USES_TERMINAL
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
    if(SOCPUPPET_COVERAGE)
      # No optimization, so that every line is still there to be counted.
      target_compile_options(${target} PRIVATE --coverage -O0)
      target_link_options(${target} PRIVATE --coverage)
      # The tests can only be run once the programs are built.
      add_dependencies(coverage ${target})
    endif()
    # Only programs are sanitized. A module that another program loads, as
    # Python loads our extension, would refuse to start in a program that is
    # not sanitized itself.
    get_target_property(type ${target} TYPE)
    if(SOCPUPPET_SANITIZE AND type STREQUAL "EXECUTABLE")
      # AddressSanitizer catches reads and writes outside an object, and uses
      # after free. UndefinedBehaviorSanitizer catches overflow, bad shifts
      # and the like, and is told to stop the program rather than only report.
      set(sanitizers -fsanitize=address,undefined -fno-sanitize-recover=undefined)
      target_compile_options(${target} PRIVATE ${sanitizers} -fno-omit-frame-pointer)
      target_link_options(${target} PRIVATE ${sanitizers})
      # The options the sanitizers should run with, built into the program.
      target_sources(${target} PRIVATE
        ${CMAKE_CURRENT_FUNCTION_LIST_DIR}/sanitizer_options.cpp)
      # Have the standard library check its own preconditions, such as an
      # index being inside a vector. The first is GCC's library, the second
      # Clang's; each ignores the other's.
      target_compile_definitions(${target} PRIVATE
        _GLIBCXX_ASSERTIONS
        _LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_EXTENSIVE)
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
