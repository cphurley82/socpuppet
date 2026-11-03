#!/usr/bin/env python3
"""socpuppet's Homebrew formula: made from a release's wheels, and tapped.

Usage: uv run python tools/tap.py render|rehearse|push|installed

The tap is the repository homebrew-socpuppet, under the same account as
socpuppet's own, so that `brew install OWNER/socpuppet/socpuppet` installs
the release on a Mac. Its formula installs the release's macOS wheel for the
Mac's processor into Homebrew's Python, with libslirp beside it.

`render` writes build/tap/Formula/socpuppet.rb from tools/socpuppet.rb.in:
for the newest Python with a wheel for both processors in build/wheelhouse,
the release's version, those wheels and their sums, platformdirs as uv.lock
pins it, and for its test the README's smaller show, which has no CPU and
fetches nothing. In CI's run of a tag of this repository the wheels are the
GitHub release's; anywhere else, the wheelhouse's own.

`rehearse` installs that formula from a tap of its own and runs its test,
then uninstalls it and removes the tap. It upgrades nothing else, and its
uninstall takes nothing else with it.

`push` commits the formula to the tap, with the token in TAP_TOKEN, in CI's
run of the tag of a release; a release candidate leaves the tap alone, and
anywhere else it says what it would push. `installed` installs the release
from the tap, as a user would, and runs the front door's tests on the
Python it is installed in (tools/test_wheel.py installed).
"""

import argparse
import hashlib
import os
import re
import shutil
import string
import subprocess
import sys
import tomllib
from pathlib import Path

import github_releases
import release

#: The formula's template, and where it is rendered.
TEMPLATE = Path("tools/socpuppet.rb.in")
FORMULA = Path("build/tap/Formula/socpuppet.rb")
#: Where the tap is cloned, to push to.
CLONE = Path("build/tap/repository")
#: The tap's name: its repository is homebrew-socpuppet, and the formula in
#: it is OWNER/socpuppet/socpuppet.
TAP = "socpuppet"
#: The tap the rehearsal installs from, a local one of its own.
REHEARSAL = f"rehearsal/{TAP}"
#: A macOS wheel of socpuppet's: its Python's minor version and its processor.
MAC_WHEEL = r"cp3(\d+)-cp3\1-macosx_\d+_\d+_(arm64|x86_64)\.whl"
#: What Homebrew calls each processor, in a formula's on_arm and on_intel.
PROCESSORS = {"arm64": "arm", "x86_64": "intel"}
#: Homebrew left to itself, not updating itself first.
QUIET_BREW = {"HOMEBREW_NO_AUTO_UPDATE": "1"}
#: Who commits a formula to the tap: GitHub Actions' bot.
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


def main() -> int:
    """Do what the command says. Returns the exit status."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    command = {
        "render": render,
        "rehearse": rehearse,
        "push": push,
        "installed": installed,
    }
    parser.add_argument("command", choices=list(command))
    args = parser.parse_args()
    command[args.command](release.repository())
    return 0


def render(root: Path) -> Path:
    """Write the formula, and return where it is."""
    name, version = release.project(root)
    with (root / "pyproject.toml").open("rb") as pyproject:
        project = tomllib.load(pyproject)["project"]
    python, wheels = _newest_wheels(root, name, version)
    where = (
        f"{github_releases.repository_url(root)}/releases/download/v{version}"
        if release.publishing(root)
        else f"file://{(root / release.WHEELHOUSE).resolve()}"
    )
    platformdirs = _locked_wheel(root, "platformdirs")
    show, shows = _smaller_show(root)
    fields = {
        "desc": project["description"],
        "homepage": github_releases.repository_url(root),
        "version": version,
        "license": project["license"],
        "python": f"python@3.{python}",
        "platformdirs_url": platformdirs["url"],
        "platformdirs_sha256": platformdirs["hash"].removeprefix("sha256:"),
        "show": show,
        "shows": shows,
    }
    for processor, wheel in wheels.items():
        homebrews = PROCESSORS[processor]
        fields[f"{homebrews}_url"] = f"{where}/{wheel.name}"
        fields[f"{homebrews}_sha256"] = hashlib.sha256(
            wheel.read_bytes()
        ).hexdigest()
    formula = root / FORMULA
    formula.parent.mkdir(parents=True, exist_ok=True)
    formula.write_text(
        string.Template((root / TEMPLATE).read_text()).substitute(fields)
    )
    print(f"🧦 Wrote {FORMULA}, for socpuppet {version} on Python 3.{python}.")
    return formula


def rehearse(root: Path) -> None:
    """Install the formula from a tap of its own, test it, and remove it."""
    formula = render(root)
    installed_as = f"{REHEARSAL}/{formula.stem}"
    # What a rehearsal stopped partway left, which would be in the way.
    _tidy(root, installed_as)
    _brew(root, "tap-new", "--no-git", REHEARSAL)
    tap = Path(_brew(root, "--repository", REHEARSAL, capture=True).strip())
    (tap / "Formula").mkdir(parents=True, exist_ok=True)
    shutil.copy(formula, tap / "Formula" / formula.name)
    try:
        # 💡 Installing a formula would otherwise upgrade any dependency
        # this machine has that is out of date.
        _brew(root, "install", installed_as, HOMEBREW_NO_INSTALL_UPGRADE="1")
        _brew(root, "test", installed_as)
    finally:
        _tidy(root, installed_as)


def _tidy(root: Path, installed_as: str) -> None:
    """Uninstall the rehearsal's formula and remove its tap, if they are.

    Neither stops anything if it fails, so that a failure before it is the
    one reported.
    """
    # ⚠️ An uninstall would otherwise take every dependency no formula
    # needs any more, whatever was built against it outside Homebrew.
    for command, settings in (
        (("uninstall", installed_as), {"HOMEBREW_NO_AUTOREMOVE": "1"}),
        (("untap", "--force", REHEARSAL), {}),
    ):
        subprocess.run(
            ["brew", *command],
            cwd=root,
            env={**os.environ, **QUIET_BREW, **settings},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def push(root: Path) -> None:
    """Commit the formula to the tap, in CI's run of the tag of a release."""
    formula = render(root)
    _, version = release.project(root)
    if not release.publishing(root) or release.candidate(version):
        print(
            "🧦 Only CI's run of the tag of a release, not of a release "
            f"candidate, pushes {FORMULA.relative_to('build/tap')} to the tap."
        )
        return
    clone = root / CLONE
    shutil.rmtree(clone, ignore_errors=True)
    _git(root, "clone", "--quiet", "--depth", "1", _tap_url(root), str(clone))
    (clone / "Formula").mkdir(exist_ok=True)
    shutil.copy(formula, clone / "Formula" / formula.name)
    _git(clone, "add", "Formula")
    unchanged = (
        subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=clone
        ).returncode
        == 0
    )
    if unchanged:
        print(f"🧦 The tap has socpuppet {version} already.")
        return
    _git(
        clone,
        *("commit", "--quiet", "-m", f"socpuppet {version}"),
        settings=(
            *("-c", "user.name=github-actions[bot]"),
            *("-c", f"user.email={BOT_EMAIL}"),
        ),
    )
    _git(clone, "push", "--quiet", "origin", "HEAD")
    print(f"🧦 Pushed socpuppet {version} to the tap.")


def installed(root: Path) -> None:
    """Install the release from the tap, and run the front door on it."""
    name, version = release.project(root)
    if not release.publishing(root) or release.candidate(version):
        print(
            "🧦 Only CI's run of the tag of a release installs it from the "
            "tap: a release candidate is not in it."
        )
        return
    formula = f"{github_releases.owner(root)}/{TAP}/{name}"
    _brew(root, "install", formula, HOMEBREW_NO_INSTALL_UPGRADE="1")
    [python] = [
        each
        for each in _brew(
            root, "deps", "--direct", "--formula", formula, capture=True
        ).split()
        if each.startswith("python@")
    ]
    prefix = _brew(root, "--prefix", python, capture=True).strip()
    interpreter = f"{prefix}/bin/python{python.removeprefix('python@')}"
    if (
        subprocess.run(
            [
                str(root / "tools" / "test_wheel.py"),
                *("installed", interpreter),
                "tests/python/test_front_door.py",
            ],
            cwd=root,
        ).returncode
        != 0
    ):
        sys.exit("The front door failed on socpuppet as the tap installs it.")


def _newest_wheels(
    root: Path, name: str, version: str
) -> tuple[int, dict[str, Path]]:
    """The newest Python with a wheel for both processors, and the wheels."""
    found: dict[int, dict[str, Path]] = {}
    pattern = re.compile(re.escape(f"{name}-{version}-") + MAC_WHEEL)
    for wheel in (root / release.WHEELHOUSE).glob("*.whl"):
        if match := pattern.fullmatch(wheel.name):
            found.setdefault(int(match[1]), {})[match[2]] = wheel
    both = [python for python, wheels in found.items() if len(wheels) == 2]
    if not both:
        missing = sorted(
            {
                processor
                for wheels in found.values() or [{}]
                for processor in PROCESSORS
                if processor not in wheels
            }
        )
        sys.exit(
            f"There is no Python with a macOS wheel of {name} {version} for "
            f"both processors in {release.WHEELHOUSE}: none for "
            f"{' or '.join(missing)}. The wheel job builds them, on a Mac of "
            "each."
        )
    python = max(both)
    return python, found[python]


def _locked_wheel(root: Path, package: str) -> dict[str, str]:
    """A package's wheel, as uv.lock pins it: its url and its hash."""
    with (root / "uv.lock").open("rb") as lock:
        [locked] = [
            each
            for each in tomllib.load(lock)["package"]
            if each["name"] == package
        ]
    [wheel] = locked["wheels"]
    return {"url": str(wheel["url"]), "hash": str(wheel["hash"])}


def _smaller_show(root: Path) -> tuple[str, str]:
    """The README's smaller show, and the first line it prints.

    The show is indented as the formula's test has it.
    """
    readme = (root / "README.md").read_text()
    section = readme.partition("## A smaller show")[2].split("\n## ", 1)[0]
    code = re.search(r"^```python\n(.*?)^```", section, re.M | re.S)
    printed = re.search(r"^```text\n(.*?)\n", section, re.M | re.S)
    if not code or not printed:
        sys.exit(
            "README.md's A smaller show has no Python, or not what it "
            "prints, for the formula's test."
        )
    show = "".join(
        f"      {line}" if line.strip() else line
        for line in code[1].splitlines(keepends=True)
    ).rstrip("\n")
    # In single quotes in Ruby, where only a backslash and a quote are
    # anything but themselves.
    shows = printed[1].strip().replace("\\", "\\\\").replace("'", "\\'")
    return show, shows


def _tap_url(root: Path) -> str:
    """Where the tap is, with the token that may push to it."""
    if url := os.environ.get("SOCPUPPET_TAP_URL"):
        return url
    token = os.environ.get("TAP_TOKEN")
    if not token:
        sys.exit(
            "There is no TAP_TOKEN to push to the tap with: the repository's "
            f"secret of that name, a token that may write to homebrew-{TAP} "
            "(docs/development.md, The release)."
        )
    owner = github_releases.owner(root)
    return (
        f"https://x-access-token:{token}@github.com/{owner}/homebrew-{TAP}.git"
    )


def _brew(
    root: Path, *arguments: str, capture: bool = False, **env: str
) -> str:
    """Ask Homebrew for something, and stop if it cannot."""
    done = subprocess.run(
        ["brew", *arguments],
        cwd=root,
        env={**os.environ, **QUIET_BREW, **env},
        stdout=subprocess.PIPE if capture else None,
        text=True,
    )
    if done.returncode != 0:
        sys.exit(f"`brew {' '.join(arguments)}` failed, and says why above.")
    return done.stdout or ""


def _git(
    directory: Path,
    command: str,
    *arguments: str,
    settings: tuple[str, ...] = (),
) -> None:
    """Ask git for something, and stop if it cannot.

    What failed is named without its arguments, which may hold the token.
    """
    done = subprocess.run(
        ["git", *settings, command, *arguments], cwd=directory
    )
    if done.returncode != 0:
        sys.exit(f"`git {command}` failed, and says why above.")


if __name__ == "__main__":
    sys.exit(main())
