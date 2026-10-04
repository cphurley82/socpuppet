"""cmake/DevChecks.cmake: compiler warnings in our own code."""

import pytest


@pytest.fixture(scope="module")
def developer_mode(cmake_project):
    """The project, configured with developer mode on.

    It has one program per scenario, named after it.
    """
    scenarios = {
        "unused_variable": UNUSED_VARIABLE,
        **{name: source for name, (source, _) in OTHER_WARNINGS.items()},
    }
    project = cmake_project(
        {f"{name}.cpp": source for name, source in scenarios.items()},
        "".join(
            f"add_executable({name} {name}.cpp)\nsocpuppet_dev_checks({name})\n"
            for name in scenarios
        ),
    )
    project.configure("SOCPUPPET_DEVELOPER_MODE=ON")
    return project


UNUSED_VARIABLE = """\
int main() {
  int unused = 0;
  return 0;
}
"""


def test_in_developer_mode_an_unused_variable_in_our_code_fails_the_build(
    developer_mode,
):
    result = developer_mode.build("unused_variable")

    assert result.returncode != 0
    assert "unused_variable.cpp:2" in result.stdout


# Each scenario's source, and the line of it that the compiler should
# object to.
OTHER_WARNINGS = {
    "unused_parameter": (
        """\
int Twice(int number, int unused) { return number * 2; }

int main() { return Twice(1, 2); }
""",
        1,
    ),
    "shadowed_variable": (
        """\
int main() {
  int count = 0;
  {
    int count = 1;
    static_cast<void>(count);
  }
  return count;
}
""",
        4,
    ),
    "narrowing_conversion": (
        """\
int main(int argc, char**) {
  long long wide = argc;
  int narrow = wide;
  return narrow;
}
""",
        3,
    ),
    "sign_conversion": (
        """\
int main(int argc, char**) {
  unsigned count = argc;
  return static_cast<int>(count);
}
""",
        2,
    ),
    "zero_length_array": (
        """\
int main() {
  int nothing[0];
  return static_cast<int>(sizeof(nothing));
}
""",
        2,
    ),
}


@pytest.mark.parametrize("scenario", OTHER_WARNINGS)
def test_in_developer_mode_other_kinds_of_warning_fail_the_build_too(
    developer_mode, scenario
):
    _, line = OTHER_WARNINGS[scenario]

    result = developer_mode.build(scenario)

    assert result.returncode != 0
    assert f"{scenario}.cpp:{line}" in result.stdout


def test_without_developer_mode_the_same_unused_variable_builds(cmake_project):
    project = cmake_project(
        {"unused_variable.cpp": UNUSED_VARIABLE},
        "add_executable(unused_variable unused_variable.cpp)\n"
        "socpuppet_dev_checks(unused_variable)\n",
    )
    project.configure()

    result = project.build("unused_variable")

    assert result.returncode == 0, result.stdout
