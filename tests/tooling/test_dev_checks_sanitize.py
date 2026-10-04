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
