"""tools/cleanup.py: what is in build/, who made it, and clearing it away.

Each test runs the tool as a person would, on a throwaway repository with
build trees of a few megabytes, and reads what it says and what it left.
"""

import collections
import importlib.util
import json
import os
import pty
import re
import shutil
import subprocess
import sys
import sysconfig
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CLEANUP = REPO / "tools" / "cleanup.py"
MEGABYTE = 1024 * 1024


def load(name):
    """A script of tools/, as a module.

    A script imports its siblings, as it does when it is run, from tools/.
    """
    if str(REPO / "tools") not in sys.path:
        sys.path.insert(0, str(REPO / "tools"))
    spec = importlib.util.spec_from_file_location(
        name, REPO / "tools" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cleanup(repo):
    """Run tools/cleanup.py over the throwaway repository.

    The repository ignores what the real one does.
    """
    shutil.copy(REPO / ".gitignore", repo / ".gitignore")

    def run(*args, no_color=True):
        env = {k: v for k, v in os.environ.items() if k != "NO_COLOR"}
        if no_color:
            env["NO_COLOR"] = "1"
        return subprocess.run(
            [sys.executable, str(CLEANUP), "--root", str(repo), *args],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )

    return run


@pytest.fixture
def cleanup_on_a_terminal(repo, monkeypatch):
    """Run tools/cleanup.py with its output going to a terminal.

    Returns what the terminal was sent.
    """
    # The developer's own preference must not decide the outcome.
    monkeypatch.delenv("NO_COLOR", raising=False)

    def run():
        ours, theirs = pty.openpty()
        process = subprocess.Popen(
            [sys.executable, str(CLEANUP), "--root", str(repo)],
            stdout=theirs,
            stderr=theirs,
        )
        os.close(theirs)
        sent = b""
        while True:
            try:
                chunk = os.read(ours, 4096)
            except OSError:  # Linux reports the far end closing as an error.
                break
            if not chunk:
                break
            sent += chunk
        os.close(ours)
        process.wait()
        return sent.decode("utf-8")

    return run


def fill(repo, path, megabytes):
    """Write a file of `megabytes` at `path`, under the repository."""
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(os.urandom(int(megabytes * MEGABYTE)))
    return file


BUILD_QBOX = load("build_qbox")
#: QBox's checkout and QEMU's, from the top of the repository, and the name
#: of a patch for each.
Patched = collections.namedtuple("Patched", "path patch")
QBOX, QEMU = (
    Patched(each.in_repository().as_posix(), each.glob.replace("*", "spam"))
    for each in (BUILD_QBOX.QBOX, BUILD_QBOX.QEMU)
)

#: A patch of the kind cmake/patches holds: it changes spam.txt from "one"
#: to "two", and adds eggs.txt.
PATCH = """\
diff --git a/spam.txt b/spam.txt
--- a/spam.txt
+++ b/spam.txt
@@ -1 +1 @@
-one
+two
diff --git a/eggs.txt b/eggs.txt
new file mode 100644
--- /dev/null
+++ b/eggs.txt
@@ -0,0 +1 @@
+eggs
"""

#: What a checkout holds, as PATCH finds it: not yet applied, applied, or
#: changed by an older patch, so that it neither applies nor reverses.
CHECKOUTS = {
    "unpatched": {"spam.txt": "one\n"},
    "patched": {"spam.txt": "two\n", "eggs.txt": "eggs\n"},
    "patched by an older patch": {"spam.txt": "three\n", "eggs.txt": "eggs\n"},
}


def checkout(repo, which, state):
    """QBox's checkout or QEMU's, `which`, of one commit, and a patch for it.

    `state` is one of CHECKOUTS. The patch is written to cmake/patches.
    """
    tree = repo / which.path
    tree.mkdir(parents=True)
    git = ("git", "-C", str(tree))
    subprocess.run([*git, "init", "--quiet"], check=True)
    (tree / "spam.txt").write_text("one\n")
    subprocess.run([*git, "add", "spam.txt"], check=True)
    subprocess.run([*git, "commit", "--quiet", "-m", "spam"], check=True)
    for name, text in CHECKOUTS[state].items():
        (tree / name).write_text(text)
    write_patch(repo, which.patch)
    return tree


def write_patch(repo, name):
    """Write PATCH to cmake/patches as `name`, and return its path."""
    patches = repo / "cmake" / "patches"
    patches.mkdir(parents=True, exist_ok=True)
    (patches / name).write_text(PATCH)
    return patches / name


def line_of(output, path):
    """The columns of the line of the report that names `path`."""
    (line,) = [each for each in output.splitlines() if f" {path} " in each]
    return re.split(r"\s{2,}", line.strip())


def test_the_report_lists_each_owned_tree_as_current_with_its_size_who_makes_it_how_long_that_takes_and_the_level_that_removes_it(
    repo, cleanup
):
    fill(repo, "build/dev/spam.o", 3)
    fill(repo, "build/qbox/install/eggs.so", 2)

    ran = cleanup()

    assert ran.returncode == 0, ran.stdout
    assert line_of(ran.stdout, "build/dev") == [
        "current",
        "build/dev",
        "3.0 MB",
        "the presets (CMakePresets.json)",
        "minutes",
        "trees",
    ]
    assert line_of(ran.stdout, "build/qbox") == [
        "current",
        "build/qbox",
        "2.0 MB",
        "tools/build_qbox.py",
        "about an hour",
        "everything",
    ]


def test_the_table_of_owned_trees_covers_every_tree_a_tool_of_today_builds_in():
    owned = [tree.path for tree in load("cleanup").TREES]

    assert {
        path
        for path in trees_the_tools_build_in()
        if not any(owned_by(path, tree) for tree in owned)
    } == set()


def trees_the_tools_build_in():
    """Every path under build/ that ci.py, the presets or pyproject names."""
    runner = load("ci")
    presets = json.loads((REPO / "CMakePresets.json").read_text())
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    return {
        *(
            used
            for job in runner.JOBS
            for used in job.uses_now()
            if used.startswith("build/")
        ),
        str(runner.LOGS.relative_to(runner.REPO)),
        runner.WHEELHOUSE,
        runner.SDIST,
        runner.CCACHE,
        *(
            preset["binaryDir"].removeprefix("${sourceDir}/")
            for preset in presets["configurePresets"]
            if "binaryDir" in preset
        ),
        pyproject["tool"]["scikit-build"]["build-dir"],
    }


def owned_by(path, tree):
    """Whether `path` is the owned `tree` or under it."""
    return path == tree or path.startswith(f"{tree}/")


def test_with_nothing_in_build_the_report_says_there_is_nothing_to_clean(
    cleanup,
):
    ran = cleanup()

    assert ran.returncode == 0, ran.stdout
    assert "Nothing to clean" in ran.stdout


def test_on_a_terminal_the_report_colors_current_green(
    repo, cleanup_on_a_terminal
):
    fill(repo, "build/dev/spam.o", 1)

    assert "\x1b[32mcurrent" in cleanup_on_a_terminal()


def test_the_report_is_plain_when_stdout_is_not_a_terminal(repo, cleanup):
    fill(repo, "build/dev/spam.o", 1)

    ran = cleanup(no_color=False)

    assert "current" in ran.stdout
    assert "\x1b" not in ran.stdout


def test_what_is_under_build_that_no_tool_of_today_makes_is_unused_with_its_size(
    repo, cleanup
):
    fill(repo, "build/speed-x/spam.o", 2)
    fill(repo, "build/asmjit/eggs.a", 1)
    fill(repo, "build/spam.log", 0.5)

    ran = cleanup()

    assert ran.returncode == 0, ran.stdout
    for path, size in (
        ("build/speed-x", "2.0 MB"),
        ("build/asmjit", "1.0 MB"),
        ("build/spam.log", "512.0 KB"),
    ):
        assert line_of(ran.stdout, path) == [
            "unused",
            path,
            size,
            "no tool of today",
            "nothing",
            "unused",
        ]


def test_an_ignored_leftover_outside_build_is_unused(repo, cleanup):
    for leftover in ("cable.pcap", ".coverage", "dist/spam.whl"):
        fill(repo, leftover, 1)
    fill(repo, "python/spam.egg-info/PKG-INFO", 1)

    ran = cleanup()

    for path in ("cable.pcap", ".coverage", "dist", "python/spam.egg-info"):
        assert line_of(ran.stdout, path) == [
            "unused",
            path,
            "1.0 MB",
            "a leftover outside build/",
            "nothing",
            "unused",
        ]


def test_what_git_ignores_that_is_no_leftover_is_not_reported(repo, cleanup):
    fill(repo, ".venv/lib/spam.py", 1)
    fill(repo, "tools/__pycache__/spam.pyc", 1)

    ran = cleanup()

    assert ".venv" not in ran.stdout
    assert "__pycache__" not in ran.stdout


def test_a_leftover_by_its_name_that_git_does_not_ignore_is_not_reported(
    repo, cleanup
):
    with (repo / ".gitignore").open("a") as gitignore:
        gitignore.write("!spam.pcap\n")
    fill(repo, "spam.pcap", 1)

    ran = cleanup()

    assert "spam.pcap" not in ran.stdout


def test_an_extension_built_for_another_platform_is_unused_and_this_platforms_is_current(
    repo, cleanup
):
    this = f"python/socpuppet/_core{sysconfig.get_config_var('EXT_SUFFIX')}"
    other = "python/socpuppet/_core.cpython-312-spam-eggs.so"
    fill(repo, this, 1)
    fill(repo, other, 1)

    ran = cleanup()

    assert line_of(ran.stdout, this) == [
        "current",
        this,
        "1.0 MB",
        "the presets (CMakePresets.json)",
        "minutes",
        "trees",
    ]
    assert line_of(ran.stdout, other) == [
        "unused",
        other,
        "1.0 MB",
        "a build for another platform",
        "nothing",
        "unused",
    ]


def test_the_report_totals_what_each_level_would_free_each_with_the_levels_before_it(
    repo, cleanup
):
    fill(repo, "build/speed-x/spam.o", 1)
    fill(repo, "build/dev/spam.o", 2)
    fill(repo, "build/qbox/spam.o", 3)

    ran = cleanup()

    assert (
        "Each level would free: unused 1.0 MB; trees 3.0 MB; everything 6.0 MB."
        in ran.stdout
    )


def test_a_counter_left_under_a_preset_tree_is_stale_and_repair_deletes_only_it(
    repo, cleanup
):
    counter = fill(repo, "build/dev/a/b.gcda", 0.25)
    beside = fill(repo, "build/dev/a/b.o", 1)

    reported = cleanup()
    repaired = cleanup("repair")

    assert line_of(reported.stdout, "build/dev/**/*.gcda") == [
        "stale",
        "build/dev/**/*.gcda",
        "256.0 KB",
        "1 counter of an interrupted coverage run",
        "nothing",
        "repair",
    ]
    assert "🧹 deleted 1 *.gcda under build/dev" in repaired.stdout
    assert not counter.exists()
    assert beside.exists()


def test_a_counter_in_a_tree_the_presets_do_not_make_is_not_stale_and_repair_keeps_it(
    repo, cleanup
):
    counter = fill(repo, "build/qbox/build/spam.gcda", 0.25)

    reported = cleanup()
    cleanup("repair")

    assert "build/qbox/**/*.gcda" not in reported.stdout
    assert counter.exists()


def test_repair_removes_nothing_unused_and_no_tree(repo, cleanup):
    unused = fill(repo, "build/speed-x/spam.o", 1)
    tree = fill(repo, "build/dev/spam.o", 1)
    leftover = fill(repo, "cable.pcap", 1)

    ran = cleanup("repair")

    assert ran.returncode == 0, ran.stdout
    assert unused.exists()
    assert tree.exists()
    assert leftover.exists()


def test_a_qbox_patch_that_neither_applies_nor_reverses_makes_the_checkout_stale_and_the_report_warns_of_lost_edits(
    repo, cleanup
):
    checkout(repo, QBOX, "patched by an older patch")

    ran = cleanup()

    assert ran.returncode == 0, ran.stdout
    state, path, _size, *rest = line_of(ran.stdout, QBOX.path)
    assert [state, path, *rest] == [
        "stale",
        QBOX.path,
        f"{QBOX.patch} neither applies nor reverses",
        "minutes",
        "repair",
    ]
    assert (
        "⚠️ repair runs git reset --hard and git clean -fd in "
        f"{QBOX.path}, discarding uncommitted edits" in ran.stdout
    )


def test_repair_puts_the_checkout_back_at_its_commit_so_the_patch_applies_and_says_so(
    repo, cleanup
):
    src = checkout(repo, QBOX, "patched by an older patch")

    ran = cleanup("repair")

    assert f"🧹 reset {QBOX.path}" in ran.stdout
    assert applies(src, repo / "cmake/patches" / QBOX.patch)
    assert not (src / "eggs.txt").exists()


def applies(checkout, patch):
    """Whether `patch` applies to `checkout` as it stands."""
    return (
        subprocess.run(
            ["git", "-C", str(checkout), "apply", "--check", str(patch)],
            capture_output=True,
        ).returncode
        == 0
    )


def test_the_report_alone_leaves_a_stale_checkout_as_it_is(repo, cleanup):
    src = checkout(repo, QBOX, "patched by an older patch")

    cleanup()

    assert (src / "spam.txt").read_text() == "three\n"
    assert (src / "eggs.txt").exists()


@pytest.mark.parametrize("state", ["unpatched", "patched"])
def test_a_checkout_its_patch_applies_to_or_is_applied_in_is_not_stale_and_repair_leaves_it(
    repo, cleanup, state
):
    src = checkout(repo, QBOX, state)
    before = {name: (src / name).read_text() for name in CHECKOUTS[state]}

    reported = cleanup()
    repaired = cleanup("repair")

    assert QBOX.path not in reported.stdout
    assert "reset" not in repaired.stdout
    assert {name: (src / name).read_text() for name in before} == before


def test_qemus_checkout_is_stale_and_repaired_the_same_way_by_the_libqemu_patches(
    repo, cleanup
):
    src = checkout(repo, QEMU, "patched by an older patch")

    reported = cleanup()
    repaired = cleanup("repair")

    assert line_of(reported.stdout, QEMU.path)[0] == "stale"
    assert f"🧹 reset {QEMU.path}" in repaired.stdout
    assert (src / "spam.txt").read_text() == "one\n"


def test_a_qbox_patch_with_no_checkout_to_go_in_is_not_a_fault(repo, cleanup):
    write_patch(repo, QBOX.patch)

    ran = cleanup("repair")

    assert ran.returncode == 0, ran.stdout
    assert "stale" not in ran.stdout


def test_unused_removes_what_is_unused_and_says_so_with_its_size(repo, cleanup):
    fill(repo, "build/speed-x/spam.o", 1)
    fill(repo, "cable.pcap", 1)
    tree = fill(repo, "build/dev/spam.o", 1)
    qbox = fill(repo, "build/qbox/install/eggs.so", 1)

    ran = cleanup("unused")

    assert ran.returncode == 0, ran.stdout
    assert "🧹 removed build/speed-x (1.0 MB)" in ran.stdout
    assert "🧹 removed cable.pcap (1.0 MB)" in ran.stdout
    assert not (repo / "build/speed-x").exists()
    assert not (repo / "cable.pcap").exists()
    assert tree.exists()
    assert qbox.exists()


def test_trees_removes_what_unused_does_and_the_trees_remade_in_minutes_and_keeps_qbox_and_the_firmware(
    repo, cleanup
):
    unused = fill(repo, "build/speed-x/spam.o", 1)
    tree = fill(repo, "build/dev/spam.o", 1)
    qbox = fill(repo, "build/qbox/install/eggs.so", 1)
    firmware = fill(repo, "build/firmware/zephyr.elf", 1)

    ran = cleanup("trees")

    assert ran.returncode == 0, ran.stdout
    assert not unused.exists()
    assert not tree.exists()
    assert qbox.exists()
    assert firmware.exists()


def test_everything_removes_qbox_and_the_firmware_and_leaves_the_venv_and_the_local_settings(
    repo, cleanup
):
    qbox = fill(repo, "build/qbox/install/eggs.so", 1)
    firmware = fill(repo, "build/firmware/zephyr.elf", 1)
    venv = fill(repo, ".venv/lib/spam.py", 1)
    settings = fill(repo, ".claude/settings.local.json", 1)

    ran = cleanup("everything")

    assert ran.returncode == 0, ran.stdout
    assert not qbox.exists()
    assert not firmware.exists()
    assert venv.exists()
    assert settings.exists()


def test_everything_warns_first_of_how_long_making_it_all_again_takes(
    repo, cleanup
):
    fill(repo, "build/qbox/install/eggs.so", 1)
    fill(repo, "build/firmware/zephyr.elf", 1)

    ran = cleanup("everything")

    (warning,) = [
        line
        for line in ran.stdout.splitlines()
        if line.startswith("⚠️ everything removes")
    ]
    for tree in load("cleanup").TREES:
        if tree.level.value == "everything":
            assert f"{tree.path} ({tree.cost} to make again)" in warning
    assert ran.stdout.index(warning) < ran.stdout.index("🧹 removed")


def test_a_symlink_under_build_is_removed_and_what_it_points_at_is_kept(
    repo, cleanup, tmp_path_factory
):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    kept = fill(elsewhere, "spam.o", 1)
    (repo / "build").mkdir()
    (repo / "build/speed-x").symlink_to(elsewhere, target_is_directory=True)

    ran = cleanup("unused")

    assert ran.returncode == 0, ran.stdout
    assert not os.path.lexists(repo / "build/speed-x")
    assert kept.exists()


def test_a_level_it_does_not_know_is_refused_with_the_usage(cleanup):
    ran = cleanup("spam")

    assert ran.returncode == 2
    assert "usage: tools/cleanup.py" in ran.stdout
