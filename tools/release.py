#!/usr/bin/env python3
"""Release socpuppet: check a release, and publish it from its tag.

Usage: uv run python tools/release.py check

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
"""

import argparse
import os
import re
import runpy
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

#: The pin of the images' release, which an installed wheel fetches from.
PIN = Path("python/socpuppet/images_release.py")
#: A version a release may have: X.Y.Z, or a release candidate of one.
VERSION = re.compile(r"\d+\.\d+\.\d+(rc\d+)?")
#: Where PyPI is, unless SOCPUPPET_PYPI_URL says otherwise.
PYPI = "https://pypi.org"


def main() -> int:
    """Do what the command says. Returns the exit status."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["check"])
    parser.parse_args()
    return check(_repository())


def check(root: Path) -> int:
    """Check the release; returns 1 if anything is wrong with it, else 0."""
    with (root / "pyproject.toml").open("rb") as pyproject:
        project = tomllib.load(pyproject)["project"]
    name, version = project["name"], project["version"]
    wanted = f"v{version}"
    on_a_tag = os.environ.get("GITHUB_REF_TYPE") == "tag"
    tag = os.environ["GITHUB_REF_NAME"] if on_a_tag else wanted
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
    pypi = os.environ.get("SOCPUPPET_PYPI_URL", PYPI)
    if _found(f"{pypi}/pypi/{name}/{version}/json"):
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


def _repository() -> Path:
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
