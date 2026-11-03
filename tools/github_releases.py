"""A GitHub release of this repository's, made once, from CI.

tools/released_images.py makes the firmware images' releases, and
tools/release.py socpuppet's own; both make theirs the same way, here.
"""

import os
import subprocess
import sys
import tomllib
from pathlib import Path


def ours(root: Path) -> bool:
    """Whether CI is running on this repository, and not on a fork of it."""
    here = os.environ.get("GITHUB_REPOSITORY", "")
    return bool(here) and repository_url(root).endswith(f"/{here}")


def repository_url(root: Path) -> str:
    """Where this repository is on the web, as pyproject.toml says."""
    with (root / "pyproject.toml").open("rb") as pyproject:
        return str(tomllib.load(pyproject)["project"]["urls"]["Repository"])


def create_once(root: Path, tag: str, *arguments: str) -> bool:
    """Make the release of `tag`, unless it is published already.

    `arguments` are what `gh release create TAG` is given besides. Returns
    whether the release was made.
    """
    there = subprocess.run(
        ["gh", "release", "view", tag, "--json", "isDraft", "--jq", ".isDraft"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if there.returncode == 0:
        if there.stdout.strip() != "true":
            print(f"🧦 {tag} is already published, and is left as it was.")
            return False
        # 💡 A run stopped while uploading leaves a draft, which `gh` finds
        # as it would a release, and which nobody can fetch from.
        gh(root, "release", "delete", tag, "--yes")
    gh(root, "release", "create", tag, *arguments)
    return True


def gh(root: Path, *arguments: str) -> None:
    """Ask GitHub's command line for something, and stop if it cannot."""
    if subprocess.run(["gh", *arguments], cwd=root).returncode != 0:
        sys.exit(
            f"`gh {' '.join(arguments[:3])}` failed, and says why above. "
            "What was published already is kept: run this job again."
        )
