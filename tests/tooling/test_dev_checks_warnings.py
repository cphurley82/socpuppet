"""cmake/DevChecks.cmake: compiler warnings in our own code."""

import pytest


@pytest.fixture(scope="module")
def developer_mode(cmake_project):
    """The project, configured with developer mode on."""
    project = cmake_project(
        {"unused_variable.cpp": UNUSED_VARIABLE},
        "add_executable(unused_variable unused_variable.cpp)\n"
        "socpuppet_dev_checks(unused_variable)\n",
    )
    configured = project.configure("SOCPUPPET_DEVELOPER_MODE=ON")
    assert configured.returncode == 0, configured.stdout
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


def test_without_developer_mode_the_same_unused_variable_builds(cmake_project):
    project = cmake_project(
        {"unused_variable.cpp": UNUSED_VARIABLE},
        "add_executable(unused_variable unused_variable.cpp)\n"
        "socpuppet_dev_checks(unused_variable)\n",
    )
    project.configure()

    result = project.build("unused_variable")

    assert result.returncode == 0, result.stdout
