#!/usr/bin/env python3
"""Release socpuppet: check a release, and publish it from its tag.

Usage: uv run python tools/release.py check|pypi|github|wait

A release is made by pushing a tag, `v` and the version in pyproject.toml,
annotated with the release's notes, on a commit of main.

`check` is what every other job of a release waits for. In CI's run of a
tag it refuses one that is not `v` and the version, is not annotated, or
is not on main; anywhere it refuses a version that is not X.Y.Z or a
release candidate X.Y.ZrcN, one PyPI already has, and firmware images
whose release (python/socpuppet/images_release.py) is not published,
since an installed wheel fetches them from there. Run here, it is a dry
run, and says how to tag the release if it is not tagged yet. ⚠️ It needs a
checkout with main and the tags in it: in CI, actions/checkout with
fetch-depth 0.

`pypi` publishes the distributions, the wheels in build/wheelhouse and the
source in build/sdist, to PyPI, by its
trusted publishing, and skips any it already has. `github` makes the tag's
GitHub release, its notes the tag's message and its files the same
distributions: the project's latest, or a pre-release for a release
candidate. Each publishes only in CI's run of a tag of this repository;
anywhere else each says what it would publish. `wait` waits for PyPI's
index to list the version's source and a wheel, which pip reads, so that
what is installed next is the release: in a run of a tag for up to ten
minutes, and anywhere else it looks once.
"""

import argparse
import os
import re
import runpy
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

import github_releases

#: The pin of the images' release, which an installed wheel fetches from.
PIN = Path("python/socpuppet/images_release.py")
#: A version a release may have: X.Y.Z, or a release candidate of one.
VERSION = re.compile(r"\d+\.\d+\.\d+(rc\d+)?")
#: Where PyPI is, unless SOCPUPPET_PYPI_URL says otherwise.
PYPI = "https://pypi.org"
#: A file an index of PyPI's lists, as its simple page links it.
LISTED = re.compile(r">([^<>]+)</a>")
#: Where the jobs that build the distributions leave them: the wheels, and
#: the source.
WHEELHOUSE = Path("build/wheelhouse")
SDIST = Path("build/sdist")
#: How long a run of a tag waits for PyPI's index, and how often it looks.
PATIENCE = 600
EVERY = 5


def main() -> int:
    """Do what the command says. Returns the exit status."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    command = {"check": check, "pypi": pypi, "github": github, "wait": wait}
    parser.add_argument("command", choices=list(command))
    args = parser.parse_args()
    return command[args.command](repository())


def check(root: Path) -> int:
    """Check the release; returns 1 if anything is wrong with it, else 0."""
    name, version = project(root)
    wanted = f"v{version}"
    on_a_tag = _tag() is not None
    tag = _tag() or wanted
    problems = []
    if not VERSION.fullmatch(version):
        problems.append(
            f"{version}, the version in pyproject.toml, is not X.Y.Z or a "
            "release candidate X.Y.ZrcN."
        )
    if tag != wanted:
        problems.append(
            f"The tag is {tag}, and pyproject.toml's version is {version}: "
            f"tag {wanted}, or change the version in a pull request first."
        )
    if _git(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"):
        if _git(root, "cat-file", "-t", f"refs/tags/{tag}") != "tag":
            problems.append(
                f"{tag} has no message, which is the release's notes: "
                f"`git tag -d {tag} && git push origin :refs/tags/{tag}`, "
                f"then `git tag -a {tag}` with them and push it again."
            )
        if problem := _not_on_main(root, tag):
            problems.append(problem)
    elif on_a_tag:
        problems.append(f"There is no tag {tag} in this checkout.")
    else:
        print(
            f"🧦 {wanted} is not tagged yet. On main, "
            f'`git tag -a {wanted} -m "<the notes>" && git push origin '
            f"{wanted}` releases it."
        )
    images = _images(root)
    if not _found(f"{images}/SHA256SUMS"):
        problems.append(
            f"The images' release, {images.rsplit('/', 1)[-1]}, is not "
            "published, and an installed wheel fetches its images from "
            "there: it is made by main's first run to pass with them."
        )
    if _found(f"{_pypi()}/pypi/{name}/{version}/json"):
        problems.append(
            f"PyPI already has {name} {version}, and a version is published "
            "once: change the version in a pull request first."
        )
    for problem in problems:
        print(f"❌ {problem}")
    if problems:
        return 1
    print(f"✅ {name} {version} can be released from {tag}.")
    return 0


def pypi(root: Path) -> int:
    """Publish the distributions to PyPI, in a run of this repository's tag."""
    built = _built(root)
    if not publishing(root):
        print(_would_publish("PyPI", built))
        return 0
    _run(
        root,
        *("uv", "publish", "--trusted-publishing", "always"),
        # 💡 A run made again skips what PyPI already has.
        *("--check-url", f"{_pypi()}/simple/"),
        *(str(path) for path in built),
    )
    return 0


def github(root: Path) -> int:
    """Make the tag's GitHub release, in a run of this repository's tag."""
    name, version = project(root)
    tag = f"v{version}"
    built = _built(root)
    if not publishing(root):
        print(_would_publish(f"GitHub's release {tag}", built))
        return 0
    github_releases.create_once(
        root,
        tag,
        *("--verify-tag", "--notes-from-tag", "--title", f"{name} {version}"),
        *(("--prerelease",) if candidate(version) else ("--latest",)),
        *(str(path) for path in built),
    )
    return 0


def wait(root: Path) -> int:
    """Wait for PyPI's index to list the version's source and a wheel."""
    name, version = project(root)
    index = f"{_pypi()}/simple/{name}/"
    # 💡 Only a run that published waits: a fork's tag publishes nothing.
    patience = PATIENCE if publishing(root) else 0
    deadline = time.monotonic() + patience
    while True:
        listed = _listed(index)
        # 💡 Any wheel will do: one `uv publish` uploads all of them.
        if f"{name}-{version}.tar.gz" in listed and any(
            each.startswith(f"{name}-{version}-") and each.endswith(".whl")
            for each in listed
        ):
            print(f"✅ PyPI lists {name} {version}.")
            return 0
        if time.monotonic() >= deadline:
            waited = f" after {patience} s" if patience else ""
            sys.exit(
                f"PyPI's index, {index}, does not list {name} {version}'s "
                f"source and a wheel{waited}."
            )
        time.sleep(EVERY)


def _listed(index: str) -> set[str]:
    """The files an index's page of a project lists, by name."""
    try:
        with urllib.request.urlopen(index, timeout=30) as page:
            return set(LISTED.findall(page.read().decode()))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return set()
        raise


def publishing(root: Path) -> bool:
    """Whether this is CI's run of a tag of this repository."""
    return _tag() is not None and github_releases.ours(root)


def _would_publish(where: str, built: list[Path]) -> str:
    """What a run that does not publish says it would have."""
    listed = "\n".join(f"  {path}" for path in built)
    return (
        f"🧦 Only CI's run of a release's tag publishes to {where}:\n{listed}"
    )


def _built(root: Path) -> list[Path]:
    """The wheels and the source, from the top of the repository.

    A release is published whole, or not at all: a version is published
    once, and one without its wheels or its source stays that way.
    """
    wheels = sorted(
        p.relative_to(root) for p in (root / WHEELHOUSE).glob("*.whl")
    )
    source = sorted(
        p.relative_to(root) for p in (root / SDIST).glob("*.tar.gz")
    )
    if not wheels or not source:
        missing = " and ".join(
            what
            for what, found in (
                (f"no wheels in {WHEELHOUSE}", wheels),
                (f"no source in {SDIST}", source),
            )
            if not found
        )
        sys.exit(
            f"There are {missing}, and a release is published whole: "
            "`uv run python tools/ci.py release-check wheel` builds this "
            "machine's."
        )
    return [*wheels, *source]


def candidate(version: str) -> bool:
    """Whether a version is a release candidate's, as 0.1.0rc1 is."""
    return "rc" in version


def project(root: Path) -> tuple[str, str]:
    """The project's name and version, as pyproject.toml has them."""
    with (root / "pyproject.toml").open("rb") as pyproject:
        project = tomllib.load(pyproject)["project"]
    return str(project["name"]), str(project["version"])


def _tag() -> str | None:
    """The tag CI is running for, or None if it is not running for one."""
    if os.environ.get("GITHUB_REF_TYPE") != "tag":
        return None
    return os.environ["GITHUB_REF_NAME"]


def _pypi() -> str:
    """Where PyPI is."""
    return os.environ.get("SOCPUPPET_PYPI_URL", PYPI)


def _run(root: Path, *command: str) -> None:
    """Run a step of publishing, and stop if it fails."""
    if subprocess.run(command, cwd=root).returncode != 0:
        sys.exit(
            f"`{' '.join(command[:3])}` failed, and says why above. What was "
            "published already is kept: run this job again."
        )


def _images(root: Path) -> str:
    """Where the images an installed wheel fetches are, as its pin says."""
    return str(runpy.run_path(str(root / PIN))["URL"])


def _found(url: str) -> bool:
    """Whether a web server has `url`: False if it answers Not Found."""
    try:
        with urllib.request.urlopen(url, timeout=30):
            return True
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise


def _not_on_main(root: Path, tag: str) -> str | None:
    """What is wrong if the tag's commit is not on main, or None."""
    if not _git(root, "rev-parse", "--verify", "--quiet", "origin/main"):
        return (
            "This checkout has no origin/main to find the tag on: "
            "`git fetch origin main`, or in CI check out with fetch-depth 0."
        )
    on_main = subprocess.run(
        ["git", "merge-base", "--is-ancestor", tag, "origin/main"], cwd=root
    )
    if on_main.returncode != 0:
        return (
            f"{tag} is not on main: a release is made from a commit of "
            "main, after its pull request has passed."
        )
    return None


def _git(root: Path, *arguments: str) -> str:
    """What git prints, or nothing if it fails."""
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    ).stdout.strip()


def repository() -> Path:
    """The top of the git repository this was run in."""
    return Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout.strip()
    )


if __name__ == "__main__":
    sys.exit(main())
