"""cmake/MacSdk.cmake: on a Mac, building against a named SDK."""

import subprocess
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[2] / "cmake" / "MacSdk.cmake"

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="the SDK is a Mac's"
)

SPAM = "int main() { return 0; }\n"


def test_on_a_mac_a_build_not_told_its_sdk_does_not_look_in_usr_local_include(
    cmake_project,
):
    assert "/usr/local/include" not in search_path(cmake_project)


def test_on_a_mac_a_build_told_its_sdk_keeps_it(cmake_project, tmp_path):
    spam_sdk = another_name_for_the_sdk(tmp_path / "Spam.sdk")

    searched = search_path(cmake_project, f"CMAKE_OSX_SYSROOT={spam_sdk}")

    assert f"{spam_sdk}/usr/include" in searched


def search_path(cmake_project, *options):
    """Where the compiler looks for <...> headers, in a project that uses
    the module and is configured with `options`.

    The program is compiled with -v, so that the compiler prints them.
    """
    project = cmake_project(
        {"spam.cpp": SPAM},
        "add_executable(spam spam.cpp)\n"
        "target_compile_options(spam PRIVATE -v)\n",
        before_project=f"include({MODULE})\n",
    )
    project.configure(*options)
    built = project.build("spam")
    assert built.returncode == 0, built.stdout
    _, _, listed = built.stdout.partition("#include <...> search starts here:")
    listed, _, _ = listed.partition("End of search list.")
    return [line.strip() for line in listed.splitlines() if line.strip()]


def another_name_for_the_sdk(path):
    """A link at `path` to the SDK the compiler would use anyway: everything
    is still found, and the name shows which SDK the build was given."""
    path.symlink_to(
        subprocess.run(
            ["xcrun", "--show-sdk-path"],
            stdout=subprocess.PIPE,
            encoding="utf-8",
            check=True,
        ).stdout.strip()
    )
    return path
