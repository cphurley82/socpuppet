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


def test_after_a_build_that_reformatted_a_source_the_next_build_leaves_the_program_alone(
    project,
):
    project.configure("SOCPUPPET_DEVELOPER_MODE=ON")
    project.build("program")
    built = project.built("program").stat().st_mtime_ns

    second = project.build("program")

    assert second.returncode == 0, second.stdout
    assert project.built("program").stat().st_mtime_ns == built


def test_on_a_ci_runner_building_leaves_a_misformatted_source_as_it_is(project):
    project.configure("SOCPUPPET_DEVELOPER_MODE=ON", ci=True)

    result = project.build("program")

    assert result.returncode == 0, result.stdout
    assert (project.source / "program.cpp").read_text() == (
        "int   main( ){return 0;}\n"
    )
