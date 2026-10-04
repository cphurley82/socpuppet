"""cmake/DevChecks.cmake: building our programs with sanitizers."""

import subprocess
import sys

READS_PAST_THE_END = """\
int main(int argc, char**) {
  int* numbers = new int[4]{};
  // argc is 1, so this is numbers[4]: one past the end.
  int beyond = numbers[argc + 3];
  delete[] numbers;
  return beyond;
}
"""


def test_when_sanitizing_a_read_past_the_end_of_an_allocation_stops_the_program(
    cmake_project,
):
    project = cmake_project(
        {"reads_past_the_end.cpp": READS_PAST_THE_END},
        "add_executable(reads_past_the_end reads_past_the_end.cpp)\n"
        "socpuppet_dev_checks(reads_past_the_end)\n",
    )
    project.configure("SOCPUPPET_SANITIZE=ON")
    project.build("reads_past_the_end")

    result = project.run("reads_past_the_end")

    assert result.returncode != 0
    assert "heap-buffer-overflow" in result.stdout


INDEXES_PAST_THE_SIZE = """\
#include <cstddef>
#include <vector>

int main(int argc, char**) {
  std::vector<int> numbers(4);
  // Room for more, so that numbers[4] is still inside the allocation.
  numbers.reserve(16);
  // argc is 1, so this is numbers[4]: one past the last element.
  return numbers[static_cast<std::size_t>(argc) + 3];
}
"""


def test_when_sanitizing_an_index_past_the_size_of_a_vector_stops_the_program(
    cmake_project,
):
    project = cmake_project(
        {"indexes_past_the_size.cpp": INDEXES_PAST_THE_SIZE},
        "add_executable(indexes_past_the_size indexes_past_the_size.cpp)\n"
        "socpuppet_dev_checks(indexes_past_the_size)\n",
    )
    project.configure("SOCPUPPET_SANITIZE=ON")
    project.build("indexes_past_the_size")

    result = project.run("indexes_past_the_size")

    # Stopped by a signal (the library aborts or traps), where returning
    # whatever was read would give an exit status of zero or more.
    assert result.returncode < 0


def test_when_sanitizing_a_loadable_module_still_loads_into_a_plain_program(
    cmake_project,
):
    # The Python extension is such a module, and the interpreter that loads
    # it is not built with sanitizers.
    project = cmake_project(
        {"plugin.cpp": 'extern "C" int Answer() { return 42; }\n'},
        "add_library(plugin MODULE plugin.cpp)\n"
        'set_target_properties(plugin PROPERTIES PREFIX "" SUFFIX .so)\n'
        "socpuppet_dev_checks(plugin)\n",
    )
    project.configure("SOCPUPPET_SANITIZE=ON")
    project.build("plugin")

    loaded = subprocess.run(
        [
            sys.executable,
            "-c",
            "import ctypes, sys; print(ctypes.CDLL(sys.argv[1]).Answer())",
            str(project.built("plugin.so")),
        ],
        capture_output=True,
        text=True,
    )

    assert loaded.stdout.strip() == "42", loaded.stderr


VENDOR = """\
#include <vector>

void Append(std::vector<int>& numbers, int number) { numbers.push_back(number); }
"""

READS_WHAT_VENDOR_APPENDED = """\
#include <vector>

void Append(std::vector<int>& numbers, int number);

int main() {
  std::vector<int> numbers;
  numbers.reserve(16);
  Append(numbers, 0);
  return numbers[0];
}
"""


def test_when_sanitizing_a_vector_filled_by_a_library_that_is_not_sanitized_can_be_read(
    cmake_project,
):
    # Our dependencies are such libraries. AddressSanitizer tracks which part
    # of a vector is in use, and a library built without it does not say.
    project = cmake_project(
        {"vendor.cpp": VENDOR, "program.cpp": READS_WHAT_VENDOR_APPENDED},
        "add_library(vendor STATIC vendor.cpp)\n"
        "add_executable(program program.cpp)\n"
        "target_link_libraries(program PRIVATE vendor)\n"
        "socpuppet_dev_checks(program)\n",
    )
    project.configure("SOCPUPPET_SANITIZE=ON")
    project.build("program")

    result = project.run("program")

    assert result.returncode == 0, result.stdout
