"""cmake/DevChecks.cmake: a copy of a built library kept in a directory.

`socpuppet_copy_into(target directory)` keeps a copy of what `target`
builds in `directory`, refreshed by every build of that tree, so that
with two trees copying into one directory the copy is the last tree's to
be built, and not the last to have relinked.
"""

import pytest

SPAM = 'extern "C" int answer() { return 1; }\n'
EGGS = 'extern "C" int answer() { return 2; }\n'
#: The module each project builds, named by the test and not the toolchain.
MODULE = "answer.so"


@pytest.fixture
def copies(tmp_path):
    """Where both projects' trees copy their module to."""
    return tmp_path / "package"


@pytest.fixture
def spam_and_eggs(cmake_project, copies):
    """Two configured projects, each a module `answer`, copying into `copies`."""
    lists = (
        "add_library(answer MODULE answer.cpp)\n"
        'set_target_properties(answer PROPERTIES PREFIX "" SUFFIX .so)\n'
        f"socpuppet_copy_into(answer {copies.as_posix()})\n"
    )
    spam = cmake_project({"answer.cpp": SPAM}, lists)
    eggs = cmake_project({"answer.cpp": EGGS}, lists)
    spam.configure()
    eggs.configure()
    return spam, eggs


def test_a_build_leaves_its_copy_in_the_directory(spam_and_eggs, copies):
    spam, _ = spam_and_eggs

    spam.build("all")

    assert (copies / MODULE).read_bytes() == spam.built(MODULE).read_bytes()


def test_a_build_that_relinks_nothing_still_leaves_its_copy_and_not_the_other_trees(
    spam_and_eggs, copies
):
    spam, eggs = spam_and_eggs
    spam.build("all")
    eggs.build("all")

    spam.build("all")

    assert (copies / MODULE).read_bytes() == spam.built(MODULE).read_bytes()
