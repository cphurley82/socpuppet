"""cmake/DevChecks.cmake: building our programs with sanitizers."""

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

    # AddressSanitizer can watch a vector's spare room too. That has to be
    # off when a dependency is not built the same way, as ours are not, so
    # the standard library's own check is what must catch this.
    result = project.run(
        "indexes_past_the_size",
        environment={"ASAN_OPTIONS": "detect_container_overflow=0"},
    )

    # Stopped by a signal (the library aborts or traps), where returning
    # whatever was read would give an exit status of zero or more.
    assert result.returncode < 0
