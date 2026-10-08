# Checks applied to our own code while it is built.
#
# Include this before defining targets, then name the targets that are ours:
#
#   socpuppet_dev_checks(<program or module>...)
#   socpuppet_check_headers(<header-only library>...)
#
# Three options decide what that does. All are off unless asked for, so
# someone who only wants to build socpuppet never meets them.

option(SOCPUPPET_DEVELOPER_MODE
  "Hold our own code to the project's standards while building it" OFF)
option(SOCPUPPET_COVERAGE
  "Build our own code so that the tests record which lines they run" OFF)
option(SOCPUPPET_SANITIZE
  "Build our own programs so that memory errors and undefined behavior stop them" OFF)
set(SOCPUPPET_COVERAGE_CPP_FLOOR 0 CACHE STRING
  "The coverage target fails if the tests run less than this percentage of our C++ lines")
set(SOCPUPPET_COVERAGE_PYTHON_FLOOR 0 CACHE STRING
  "The coverage target fails if the tests run less than this percentage of our Python lines")

# The developer tools are installed next to the interpreter (pyproject.toml).
find_package(Python REQUIRED COMPONENTS Interpreter)
get_filename_component(_socpuppet_tools ${Python_EXECUTABLE} DIRECTORY)
set(_socpuppet_lint ${CMAKE_CURRENT_LIST_DIR}/../tools/lint.py)

# clang-tidy reads how each source is compiled from compile_commands.json.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# What to run the Python tests with: `${SOCPUPPET_TEST_PYTHON} -m pytest`.
# When coverage is being measured, that is the interpreter under coverage.py.
set(SOCPUPPET_TEST_PYTHON ${Python_EXECUTABLE})
if(SOCPUPPET_COVERAGE)
  list(APPEND SOCPUPPET_TEST_PYTHON -m coverage run)
endif()

# Give this label to a test that tests the tooling and runs none of our own
# code. The coverage target leaves such tests out.
set(SOCPUPPET_TOOLING_LABEL tooling)

# ---- Developer mode --------------------------------------------------------

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

if(SOCPUPPET_DEVELOPER_MODE)
  # Apple's compiler knows where its SDK is without being told, so the
  # compile commands do not say. clang-tidy is not Apple's and has to be
  # told, or it cannot find even the standard library.
  set(_socpuppet_tidy_sdk)
  if(APPLE)
    execute_process(COMMAND xcrun --show-sdk-path
      OUTPUT_VARIABLE _socpuppet_sdk
      OUTPUT_STRIP_TRAILING_WHITESPACE
      COMMAND_ERROR_IS_FATAL ANY)
    set(_socpuppet_tidy_sdk -extra-arg=-isysroot${_socpuppet_sdk})
  endif()

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

  # Compiles each header of our header-only libraries on its own, which
  # shows that it includes everything it uses. A target to ask for.
  add_custom_target(check_headers)
endif()

# ---- Coverage --------------------------------------------------------------

if(SOCPUPPET_COVERAGE)
  # gcov is the tool that reads the counters an instrumented program leaves
  # behind. Each compiler has its own.
  if(CMAKE_CXX_COMPILER_ID STREQUAL "AppleClang")
    set(_socpuppet_gcov "xcrun llvm-cov gcov")
  elseif(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    set(_socpuppet_gcov gcov)
  else()
    message(FATAL_ERROR
      "SOCPUPPET_COVERAGE is set up for GCC and Apple clang, and this "
      "compiler is ${CMAKE_CXX_COMPILER_ID}. Use one of those, or teach "
      "cmake/DevChecks.cmake which gcov goes with this one.")
  endif()
  set(_socpuppet_gcovr
    ${Python_EXECUTABLE} -m gcovr
    --root ${PROJECT_SOURCE_DIR}
    --filter ${PROJECT_SOURCE_DIR}/src/
    # The compiler leaves a file of notes beside each object, and it stays
    # when its source is taken out of the build. Such notes cannot be read
    # any more, and what they were about is not there to be measured.
    --gcov-ignore-errors=no_working_dir_found)
  set(_socpuppet_reports ${CMAKE_BINARY_DIR}/coverage)

  # The Python half. A project with no python/ directory has no Python to
  # measure, and coverage.py would stop at having no data.
  set(_socpuppet_python_erase)
  set(_socpuppet_python_reports)
  set(_socpuppet_python_floor)
  if(EXISTS ${PROJECT_SOURCE_DIR}/python)
    set(_socpuppet_coverage ${Python_EXECUTABLE} -m coverage)
    set(_socpuppet_python_erase COMMAND ${_socpuppet_coverage} erase)
    set(_socpuppet_python_reports
      COMMAND ${_socpuppet_coverage} combine
      COMMAND ${_socpuppet_coverage} html
              --directory ${_socpuppet_reports}/python)
    set(_socpuppet_python_floor
      COMMAND ${_socpuppet_coverage} report
              --fail-under ${SOCPUPPET_COVERAGE_PYTHON_FLOOR})
  endif()

  # Runs the tests, then reports which lines of the code under src/ and
  # python/ they ran. It fails if either falls below its floor.
  #
  # Both tables are printed. The line-by-line reports are web pages in
  # coverage/cpp and coverage/python in the build directory, and
  # coverage/cpp.md is the C++ table again, for CI to show on the job's page.
  add_custom_target(coverage
    # Counters add up from one run of a program to the next, so the ones
    # left by earlier runs go first.
    COMMAND ${Python_EXECUTABLE} -c
            "import pathlib, sys; [counters.unlink() for counters in pathlib.Path(sys.argv[1]).rglob('*.gcda')]"
            ${CMAKE_BINARY_DIR}
    ${_socpuppet_python_erase}
    COMMAND ${CMAKE_CTEST_COMMAND} --test-dir ${CMAKE_BINARY_DIR}
            --output-on-failure --label-exclude ${SOCPUPPET_TOOLING_LABEL}
    # Every report is written before either floor is checked, so that
    # missing one floor does not cost the other language its report.
    COMMAND ${CMAKE_COMMAND} -E make_directory ${_socpuppet_reports}/cpp
    COMMAND ${_socpuppet_gcovr}
            --gcov-executable ${_socpuppet_gcov}
            --html-details ${_socpuppet_reports}/cpp/index.html
            --markdown ${_socpuppet_reports}/cpp.md
            --json ${_socpuppet_reports}/cpp.json
            ${CMAKE_BINARY_DIR}
    ${_socpuppet_python_reports}
    COMMAND ${_socpuppet_gcovr}
            --json-add-tracefile ${_socpuppet_reports}/cpp.json
            --txt
            --fail-under-line ${SOCPUPPET_COVERAGE_CPP_FLOOR}
    ${_socpuppet_python_floor}
    WORKING_DIRECTORY ${PROJECT_SOURCE_DIR}
    COMMENT "Running the tests and measuring coverage"
    USES_TERMINAL
    VERBATIM)
endif()

# ---- Applying the checks ---------------------------------------------------

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

      # clang-tidy is given each source by its full path.
      get_target_property(sources ${target} SOURCES)
      get_target_property(directory ${target} SOURCE_DIR)
      foreach(source IN LISTS sources)
        cmake_path(ABSOLUTE_PATH source BASE_DIRECTORY ${directory})
        set_property(TARGET tidy APPEND PROPERTY SOCPUPPET_SOURCES ${source})
      endforeach()
    endif()

    if(TARGET socpuppet_format)
      add_dependencies(${target} socpuppet_format)
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
      target_compile_options(${target} PRIVATE ${sanitizers})
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
  endforeach()
endfunction()

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
