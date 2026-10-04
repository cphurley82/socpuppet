"""cmake/DevChecks.cmake: formatting the sources as part of the build."""

import pytest


@pytest.fixture
def project(cmake_project):
    """A project with one misformatted program."""
    return cmake_project(
        {"program.cpp": "int   main( ){return 0;}\n"},
        "add_executable(program program.cpp)\nsocpuppet_dev_checks(program)\n",
    )


def test_in_developer_mode_building_reformats_a_misformatted_source(project):
    project.configure("SOCPUPPET_DEVELOPER_MODE=ON")

    project.build("program")

    assert (project.source / "program.cpp").read_text() == (
        "int main() { return 0; }\n"
    )
