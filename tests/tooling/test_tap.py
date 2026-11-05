"""tools/tap.py: socpuppet's Homebrew formula, made from a release's wheels.

The tool runs for real in a throwaway repository, with a fake for brew and
a fake tools/test_wheel.py, and pushes to a bare repository standing in for
the tap's.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "tools"))
import release  # noqa: E402

FORMULA = Path("build/tap/Formula/socpuppet.rb")
#: Where the wheel jobs leave the wheels, as tools/release.py has it.
WHEELHOUSE = release.WHEELHOUSE
#: The repository the throwaway one stands for: the account, then its name.
GITHUB_REPOSITORY = "spam/eggs"
#: Where a test's fakes are, in its repository and out of git.
FAKES = "fakes"
#: The README's smaller show, as much of it as the formula's test takes.
README = """\
# socpuppet

## A smaller show

A platform does not need a CPU.

```python
import socpuppet as sp

print("spam")
```

```text
        0 ns  write 0x80000000  spam
        0 ns  read  0x80000000  spam
```

## A show with a drive in it
"""
#: socpuppet's one dependency, as uv.lock pins it.
LOCK = """\
version = 1

[[package]]
name = "platformdirs"
version = "4.13.3"
wheels = [
    { url = "https://files.example.com/platformdirs-4.13.3-py3-none-any.whl", hash = "sha256:f00d" },
]
"""


@pytest.fixture
def project(repo, git):
    """socpuppet 0.0.1, with its README, its lock and its tools beside."""
    a_version(repo, "0.0.1")
    (repo / "README.md").write_text(README)
    (repo / "uv.lock").write_text(LOCK)
    (repo / "tools").mkdir()
    for tool in (
        "tap.py",
        "release.py",
        "github_releases.py",
        "socpuppet.rb.in",
    ):
        shutil.copy(REPOSITORY / "tools" / tool, repo / "tools" / tool)
    (repo / FAKES).mkdir()
    with (repo / ".git" / "info" / "exclude").open("a") as exclude:
        exclude.write(f"/{FAKES}/\n/build/\n")
    git("add", "-A")
    git("commit", "--quiet", "-m", "socpuppet")
    return repo


@pytest.fixture
def wheels(project):
    """The macOS wheels of 0.0.1 for two Pythons, and a Linux one."""
    return build(
        project,
        "socpuppet-0.0.1-cp314-cp314-macosx_13_3_arm64.whl",
        "socpuppet-0.0.1-cp314-cp314-macosx_13_3_x86_64.whl",
        "socpuppet-0.0.1-cp315-cp315-macosx_13_3_arm64.whl",
        "socpuppet-0.0.1-cp315-cp315-macosx_13_3_x86_64.whl",
        "socpuppet-0.0.1-cp315-cp315-manylinux_2_28_x86_64.whl",
    )


@pytest.fixture
def brew(project):
    """A brew that keeps what it was asked, and with which HOMEBREW_*.

    brew.asked(what) is each line it was asked that starts with `what`, as
    `HOMEBREW_...=... | ARGUMENTS`. An install fails if the test says so
    (brew.install_fails()).
    """
    fakes = project / FAKES
    log = fakes / "brew.asked"
    program = fakes / "brew"
    program.write_text(
        f"""#!/bin/sh
echo "$(env | grep ^HOMEBREW_ | sort | tr '\\n' ' ')| $*" >> {log}
case "$1" in
  install) test ! -e {fakes / "install-fails"} ;;
  --repository) mkdir -p {fakes / "tap"}; echo {fakes / "tap"} ;;
  --prefix) echo /opt/homebrew/opt/$2 ;;
  deps) printf 'libslirp\\npython@3.15\\n' ;;
esac
"""
    )
    program.chmod(0o755)

    class Brew:
        tap = fakes / "tap"

        @staticmethod
        def asked(what=""):
            lines = log.read_text().splitlines() if log.exists() else []
            return [
                line
                for line in lines
                if line.split("| ", 1)[1].startswith(what)
            ]

        @staticmethod
        def install_fails():
            (fakes / "install-fails").touch()

    return Brew


@pytest.fixture
def test_wheel(project):
    """A tools/test_wheel.py that keeps what it was asked."""
    log = project / FAKES / "test_wheel.asked"
    (project / "tools" / "test_wheel.py").write_text(
        f"""#!{sys.executable}
import sys
with open({str(log)!r}, "a") as out:
    out.write(" ".join(sys.argv[1:]) + "\\n")
"""
    )
    (project / "tools" / "test_wheel.py").chmod(0o755)
    return lambda: log.read_text().splitlines() if log.exists() else []


@pytest.fixture
def the_tap(tmp_path_factory):
    """A bare repository standing in for the tap's, with a README in it."""
    return a_tap(tmp_path_factory.mktemp("tap") / "homebrew-socpuppet.git")


class TestRenderingTheFormula:
    def test_on_a_tag_it_installs_each_processors_wheel_from_the_github_release(
        self, project, wheels
    ):
        result = tap(project, "render", tag="v0.0.1")

        assert result.returncode == 0, result.stdout + result.stderr
        formula = (project / FORMULA).read_text()
        published = (
            f"https://example.com/{GITHUB_REPOSITORY}/releases/download/v0.0.1"
        )
        for processor in ("arm64", "x86_64"):
            name = f"socpuppet-0.0.1-cp315-cp315-macosx_13_3_{processor}.whl"
            assert f'url "{published}/{name}", using: :nounzip' in formula
            assert f'sha256 "{sha256(project / WHEELHOUSE / name)}"' in formula

    def test_off_a_tag_it_installs_the_wheels_built_here(self, project, wheels):
        result = tap(project, "render")

        assert result.returncode == 0, result.stdout + result.stderr
        wheelhouse = (project / WHEELHOUSE).resolve()
        name = "socpuppet-0.0.1-cp315-cp315-macosx_13_3_arm64.whl"
        assert (
            f'url "file://{wheelhouse}/{name}"'
            in (project / FORMULA).read_text()
        )

    def test_its_version_is_the_releases(self, project, wheels):
        tap(project, "render")

        assert 'version "0.0.1"' in (project / FORMULA).read_text()

    def test_its_desc_homepage_and_license_are_pyprojects(
        self, project, wheels
    ):
        tap(project, "render")

        formula = (project / FORMULA).read_text()
        assert 'desc "A whole SoC, with Python pulling the strings."' in formula
        assert f'homepage "https://example.com/{GITHUB_REPOSITORY}"' in formula
        assert 'license "MIT"' in formula

    def test_it_depends_on_libslirp_and_the_python_of_the_newest_wheels(
        self, project, wheels
    ):
        tap(project, "render")

        formula = (project / FORMULA).read_text()
        assert 'depends_on "libslirp"' in formula
        assert 'depends_on "python@3.15"' in formula

    def test_a_python_with_a_wheel_for_one_processor_alone_is_passed_over(
        self, project
    ):
        build(
            project,
            "socpuppet-0.0.1-cp314-cp314-macosx_13_3_arm64.whl",
            "socpuppet-0.0.1-cp314-cp314-macosx_13_3_x86_64.whl",
            "socpuppet-0.0.1-cp315-cp315-macosx_13_3_arm64.whl",
        )

        result = tap(project, "render")

        assert result.returncode == 0, result.stdout + result.stderr
        assert 'depends_on "python@3.14"' in (project / FORMULA).read_text()

    def test_with_no_python_with_a_wheel_for_both_processors_it_says_which_is_missing(
        self, project
    ):
        build(project, "socpuppet-0.0.1-cp315-cp315-macosx_13_3_arm64.whl")

        result = tap(project, "render")

        assert result.returncode != 0
        assert "x86_64" in result.stderr
        assert not (project / FORMULA).exists()

    def test_its_one_dependency_is_the_wheel_uv_lock_pins(
        self, project, wheels
    ):
        tap(project, "render")

        formula = (project / FORMULA).read_text()
        wheel = "https://files.example.com/platformdirs-4.13.3-py3-none-any.whl"
        assert f'url "{wheel}", using: :nounzip' in formula
        assert 'sha256 "f00d"' in formula

    def test_its_test_is_the_readmes_smaller_show_and_what_it_prints_first(
        self, project, wheels
    ):
        tap(project, "render")

        formula = (project / FORMULA).read_text()
        assert 'print("spam")' in formula
        assert "assert_match '0 ns  write 0x80000000  spam'" in formula

    def test_without_a_smaller_show_in_the_readme_it_says_so(
        self, project, wheels
    ):
        (project / "README.md").write_text("# socpuppet\n")

        result = tap(project, "render")

        assert result.returncode != 0
        assert "A smaller show" in result.stderr

    @pytest.mark.skipif(not shutil.which("ruby"), reason="no ruby here")
    def test_the_formula_is_valid_ruby(self, project, wheels):
        tap(project, "render")

        checked = ruby_checks(project / FORMULA)

        assert checked.returncode == 0, checked.stderr


class TestTheRehearsal:
    def test_it_installs_and_tests_the_formula_from_a_tap_of_its_own(
        self, project, wheels, brew
    ):
        result = tap(project, "rehearse")

        assert result.returncode == 0, result.stdout + result.stderr
        assert brew.asked("install ")
        assert brew.asked("test ")
        rehearsed = brew.tap / "Formula" / "socpuppet.rb"
        assert rehearsed.read_text() == (project / FORMULA).read_text()

    def test_it_brings_homebrews_list_of_formulae_up_to_date_before_installing(
        self, project, wheels, brew
    ):
        # A runner's image can be older than the Python the formula
        # depends on, and Homebrew does not update itself unasked here.
        tap(project, "rehearse")

        asked = brew.asked()
        (updated,) = brew.asked("update")
        (installed,) = brew.asked("install ")
        assert asked.index(updated) < asked.index(installed)

    def test_it_upgrades_nothing_else_this_machine_has(
        self, project, wheels, brew
    ):
        tap(project, "rehearse")

        (installed,) = brew.asked("install ")
        assert "HOMEBREW_NO_INSTALL_UPGRADE=1" in installed

    def test_it_leaves_this_machine_as_it_found_it(self, project, wheels, brew):
        # An uninstall would otherwise take every dependency no formula
        # needs any more, whatever else built against it.
        tap(project, "rehearse")

        uninstalled = brew.asked("uninstall ")
        assert uninstalled
        for each in uninstalled:
            assert "HOMEBREW_NO_AUTOREMOVE=1" in each
        assert brew.asked()[-1] in brew.asked("untap ")

    def test_when_the_install_fails_it_says_so_and_still_removes_its_tap(
        self, project, wheels, brew
    ):
        brew.install_fails()

        result = tap(project, "rehearse")

        assert result.returncode != 0
        assert "`brew install" in result.stderr
        assert brew.asked()[-1] in brew.asked("untap ")


class TestPushingToTheTap:
    def test_on_a_tag_of_a_release_the_formula_is_committed_to_the_tap(
        self, project, wheels, the_tap
    ):
        result = push(project, the_tap, tag="v0.0.1")

        assert result.returncode == 0, result.stdout + result.stderr
        formula = (project / FORMULA).read_text()
        assert pushed(the_tap, "Formula/socpuppet.rb") == formula
        assert last_message(the_tap) == "socpuppet 0.0.1"

    def test_a_formula_the_tap_has_already_is_not_pushed_again(
        self, project, wheels, the_tap
    ):
        push(project, the_tap, tag="v0.0.1")
        before = commits(the_tap)

        result = push(project, the_tap, tag="v0.0.1")

        assert result.returncode == 0, result.stdout + result.stderr
        assert commits(the_tap) == before

    def test_a_release_candidate_leaves_the_tap_alone(self, project, the_tap):
        a_version(project, "0.0.1rc1")
        build(
            project,
            "socpuppet-0.0.1rc1-cp315-cp315-macosx_13_3_arm64.whl",
            "socpuppet-0.0.1rc1-cp315-cp315-macosx_13_3_x86_64.whl",
        )
        before = commits(the_tap)

        result = push(project, the_tap, tag="v0.0.1rc1")

        assert result.returncode == 0, result.stdout + result.stderr
        assert commits(the_tap) == before

    def test_off_a_tag_it_says_what_it_would_push_and_pushes_nothing(
        self, project, wheels, the_tap
    ):
        before = commits(the_tap)

        result = push(project, the_tap)

        assert result.returncode == 0, result.stdout + result.stderr
        assert commits(the_tap) == before
        assert "Formula/socpuppet.rb" in result.stdout

    def test_the_tap_is_homebrew_socpuppet_under_the_projects_account_by_the_token(
        self, project, wheels, tmp_path
    ):
        # git is told to find GitHub, as the token reaches it, in a folder:
        # the tap is where the account's homebrew-socpuppet would be.
        github = tmp_path / "github"
        account = GITHUB_REPOSITORY.split("/")[0]
        the_tap = a_tap(github / account / "homebrew-socpuppet.git")

        result = tap(
            project,
            "push",
            tag="v0.0.1",
            TAP_TOKEN="spam",
            GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0=f"url.{github}/.insteadOf",
            GIT_CONFIG_VALUE_0="https://x-access-token:spam@github.com/",
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert last_message(the_tap) == "socpuppet 0.0.1"


class TestInstalledFromTheTap:
    def test_on_a_tag_brew_installs_it_and_the_front_door_runs_on_its_python(
        self, project, brew, test_wheel
    ):
        result = tap(project, "installed", tag="v0.0.1")

        assert result.returncode == 0, result.stdout + result.stderr
        (installed,) = brew.asked("install ")
        account = GITHUB_REPOSITORY.split("/")[0]
        assert installed.endswith(f"install {account}/socpuppet/socpuppet")
        assert test_wheel() == [
            "installed /opt/homebrew/opt/python@3.15/bin/python3.15 "
            "tests/python/test_front_door.py"
        ]

    def test_a_release_candidate_is_not_in_the_tap_and_is_not_installed(
        self, project, brew, test_wheel
    ):
        a_version(project, "0.0.1rc1")

        result = tap(project, "installed", tag="v0.0.1rc1")

        assert result.returncode == 0, result.stdout + result.stderr
        assert brew.asked() == []
        assert test_wheel() == []


def tap(repo, *arguments, tag=None, **env):
    """Run the tool; `tag` makes it a run of CI on that tag of this repository."""
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("GITHUB_", "HOMEBREW_", "GIT_CONFIG_"))
        and name not in ("TAP_TOKEN", "SOCPUPPET_TAP_URL")
    }
    if tag:
        environment |= {
            "GITHUB_REF_TYPE": "tag",
            "GITHUB_REF_NAME": tag,
            "GITHUB_REPOSITORY": GITHUB_REPOSITORY,
        }
    return subprocess.run(
        [sys.executable, str(repo / "tools" / "tap.py"), *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
        env={
            **environment,
            "PATH": f"{repo / FAKES}{os.pathsep}{os.environ['PATH']}",
            **env,
        },
    )


def push(project, the_tap, tag=None):
    """Run the tool's push, to the bare repository standing in for the tap."""
    return tap(project, "push", tag=tag, SOCPUPPET_TAP_URL=str(the_tap))


def a_version(repo, version):
    """The project is socpuppet at `version`."""
    (repo / "pyproject.toml").write_text(
        textwrap.dedent(f"""\
            [project]
            name = "socpuppet"
            version = "{version}"
            description = "A whole SoC, with Python pulling the strings."
            license = "MIT"

            [project.urls]
            Repository = "https://example.com/{GITHUB_REPOSITORY}"
        """)
    )


def build(project, *names):
    """Leave wheels in the wheelhouse, each its own bytes; returns them."""
    wheelhouse = project / WHEELHOUSE
    wheelhouse.mkdir(parents=True, exist_ok=True)
    for name in names:
        (wheelhouse / name).write_text(name)
    return names


def a_tap(bare):
    """A bare repository at `bare` with a README in it, as a new tap has."""
    bare.parent.mkdir(parents=True, exist_ok=True)
    git_in(bare.parent, "init", "--quiet", "--bare", "-b", "main", str(bare))
    work = bare.parent / "work"
    git_in(bare.parent, "clone", "--quiet", str(bare), str(work))
    (work / "README.md").write_text("A tap.\n")
    git_in(work, "add", "-A")
    git_in(work, "commit", "--quiet", "-m", "A tap")
    git_in(work, "push", "--quiet", "origin", "HEAD:main")
    shutil.rmtree(work)
    return bare


def ruby_checks(path):
    """Ruby's own check of a file's syntax."""
    return subprocess.run(
        ["ruby", "-c", str(path)], capture_output=True, text=True
    )


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_in(directory, *arguments):
    return subprocess.run(
        ["git", *arguments],
        cwd=directory,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def pushed(bare, path):
    return git_in(bare, "show", f"main:{path}")


def last_message(bare):
    return git_in(bare, "log", "-1", "--format=%s", "main").strip()


def commits(bare):
    return git_in(bare, "rev-list", "main").split()
