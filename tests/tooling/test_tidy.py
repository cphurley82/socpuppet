"""tools/tidy.py, which the tidy target runs clang-tidy through.

It is run for real, with a stand-in for run-clang-tidy.py that prints what
the test gives it, in the place of the developer tools.
"""

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TIDY = REPO / "tools" / "tidy.py"
# Where QBox's install keeps what CMake finds it by, as build_qbox.py says.
sys.path.insert(0, str(REPO / "tools"))
BUILD_QBOX = importlib.import_module("build_qbox")
#: The script tidy.py runs, whose place the stand-in takes.
RUN_CLANG_TIDY = importlib.import_module("tidy").RUN_CLANG_TIDY

#: What clang-tidy says when a source cannot be compiled.
CANNOT_COMPILE = (
    "src/spam.cpp:1:10: error: 'systemc' file not found "
    "[clang-diagnostic-error]"
)
#: A finding, of the kind it reports from a source it compiled.
FINDING = "src/spam.cpp:4:30: warning: use nullptr [modernize-use-nullptr]"


@pytest.fixture
def tidy(tmp_path):
    """Run tools/tidy.py over a tree, with run-clang-tidy.py a stand-in.

    The stand-in prints `says`, a line or the raw bytes, and exits with
    `status`. `qbox` is QBox's install, for a tree built with it.
    """

    def run(says, status, qbox=None):
        tools = tmp_path / "tools"
        tools.mkdir(exist_ok=True)
        raw = says if isinstance(says, bytes) else f"{says}\n".encode()
        (tools / RUN_CLANG_TIDY).write_text(
            "import sys\n"
            f"sys.stdout.buffer.write({raw!r})\n"
            f"sys.exit({status})\n"
        )
        return subprocess.run(
            [
                *(sys.executable, str(TIDY), "--tools", str(tools)),
                *("-p", str(tmp_path / "build" / "spam")),
                *(("--qbox", str(qbox)) if qbox else ()),
                "src/spam.cpp",
            ],
            env={**os.environ, "NO_COLOR": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )

    return run


def test_when_clang_tidy_cannot_compile_a_source_tidy_lists_no_finding_and_says_to_configure_again(
    tidy,
):
    ran = tidy(f"{CANNOT_COMPILE}\n{FINDING}", 1)

    assert ran.returncode == 1
    assert CANNOT_COMPILE in ran.stdout
    assert "configure the tree again" in ran.stdout
    assert "modernize-use-nullptr" not in ran.stdout


def test_when_qboxs_install_is_gone_tidy_says_to_build_qbox_again(
    tidy, tmp_path
):
    ran = tidy(CANNOT_COMPILE, 1, qbox=tmp_path / "gone")

    assert "uv run tools/build_qbox.py" in ran.stdout


@pytest.mark.parametrize("built_with_qbox", [False, True])
def test_when_qboxs_install_is_there_or_the_tree_has_none_tidy_says_nothing_of_building_qbox(
    tidy, tmp_path, built_with_qbox
):
    qbox = None
    if built_with_qbox:
        qbox = tmp_path / "install"
        package = qbox / BUILD_QBOX.PACKAGE
        package.parent.mkdir(parents=True)
        package.touch()

    ran = tidy(CANNOT_COMPILE, 1, qbox=qbox)

    assert "build_qbox" not in ran.stdout


@pytest.mark.parametrize("status", [0, 1])
def test_when_clang_tidy_compiles_every_source_its_output_and_status_pass_through(
    tidy, status
):
    ran = tidy(FINDING, status)

    assert ran.returncode == status
    assert ran.stdout == f"{FINDING}\n"


def test_a_byte_clang_tidy_prints_that_is_not_utf_8_passes_through_and_is_no_crash(
    tidy,
):
    ran = tidy(FINDING.encode() + b" \xff\n", 1)

    assert ran.returncode == 1
    assert FINDING in ran.stdout
    assert "Traceback" not in ran.stdout
