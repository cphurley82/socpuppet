"""Name the release of the firmware images these sources ask for, and make it.

Usage: uv run python tools/released_images.py COMMAND [FILE...]

COMMAND is tag, check, write or publish.

The wheel carries no firmware. It fetches each image the first time it is
needed, from a release named for the sources the images are built from
(python/socpuppet/images.py), so the same sources always ask for the same
release and new sources for a new one. Those sources are the ones the
firmware's own caches are keyed on, in .github/workflows/firmware.yml: a
change that would build a new image is the same change here.

`tag` prints the release's tag. `write` writes python/socpuppet/
images_release.py, the pin the package reads, when it is named in FILE;
`check` exits non-zero if it is not what `write` would leave. tools/lint.py
runs `check`, or `write` with --fix.

`publish` makes the release's files in build/images from the images in
build/firmware, each gzipped, and creates the release if this is a run of CI
on this repository's main and there is none yet. 💡 The first build of some
sources stays: images are not built the same twice, and a wheel may have
fetched those. Any other run says what it would have published. CI's `images`
job runs it, once the tests have passed on those images.
"""

import argparse
import fnmatch
import gzip
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import generated

#: Where the firmware's jobs are, whose cache keys say what it is built from.
WORKFLOW = Path(".github/workflows/firmware.yml")
#: One of those cache keys, which all start with the word firmware. The others
#: in that file are the keys of the tools that build it.
FIRMWARE_KEY = re.compile(r"key: (firmware-.*)")
#: How much of the hash a tag keeps: enough that no two firmwares share one.
TAG_DIGITS = 12
#: Where the firmware's jobs leave their images, with the logs of the build
#: beside them when it was built here, and the trees it was built from.
BUILT = Path("build/firmware")
#: Where the release's files are made.
ASSETS = Path("build/images")
NOTES = "NOTES.md"
#: What is built from what: each upstream's version, and where its source is.
VERSIONS = Path("firmware/versions.toml")


def main() -> int:
    """Do what the command says. Returns the exit status."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["tag", "check", "write", "publish"])
    parser.add_argument("files", nargs="*", type=Path, metavar="FILE")
    args = parser.parse_args()
    root = _repository()
    if args.command == "tag":
        print(tag(root))
        return 0
    if args.command == "publish":
        publish(root)
        return 0
    return generated.settle(
        args.command,
        {path: pin(root) for path in args.files},
        "the firmware's sources",
    )


def tag(root: Path) -> str:
    """The tag of the release built from the sources in the repository."""
    digest = hashlib.sha256()
    for name in _sources(root):
        digest.update(name.encode() + b"\0")
        digest.update(hashlib.sha256((root / name).read_bytes()).digest())
    return f"images-{digest.hexdigest()[:TAG_DIGITS]}"


def publish(root: Path) -> None:
    """Make the release's files, and on main make the release if it is new."""
    name = tag(root)
    assets = _make_assets(root)
    listed = "\n".join(f"  {asset}" for asset in assets)
    here = os.environ.get("GITHUB_REPOSITORY", "")
    if os.environ.get("GITHUB_REF_NAME") != "main" or not (
        here and _repository_url(root).endswith(f"/{here}")
    ):
        print(f"🧦 Only a run on main publishes {name}, which is:\n{listed}")
        return
    there = subprocess.run(
        [
            "gh",
            "release",
            "view",
            name,
            "--json",
            "isDraft",
            "--jq",
            ".isDraft",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if there.returncode == 0:
        if there.stdout.strip() != "true":
            print(f"🧦 {name} is already published, and is left as it was.")
            return
        # 💡 A run stopped while uploading leaves a draft, which `gh` finds
        # as it would a release, and which no wheel can fetch from.
        _gh(root, "release", "delete", name, "--yes")
    _gh(
        root,
        *("release", "create", name),
        *("--title", f"Firmware images {name}"),
        *("--target", _commit(root)),
        *("--notes-file", str(ASSETS / NOTES)),
        # 💡 The latest release of a project is socpuppet's own, one day.
        "--latest=false",
        *(str(asset) for asset in assets),
    )
    print(f"🧦 Published {name}:\n{listed}")


def _gh(root: Path, *arguments: str) -> None:
    """Ask GitHub's command line for something, and stop if it cannot."""
    if subprocess.run(["gh", *arguments], cwd=root).returncode != 0:
        sys.exit(
            f"`gh {' '.join(arguments[:3])}` failed, and says why above. "
            "Nothing is published until its last step: run this job again."
        )


def _make_assets(root: Path) -> list[Path]:
    """Write the release's files, and return them from the top of the repo.

    The notes are written too, and are left out of what is returned: they
    are what the release says, and not one of its files.
    """
    images = (
        sorted(
            path
            for path in (root / BUILT).iterdir()
            if path.is_file() and path.suffix != ".log"
        )
        if (root / BUILT).is_dir()
        else []
    )
    if not images:
        sys.exit(
            f"There are no images in {root / BUILT}, so there is nothing to "
            "publish. `uv run firmware/build.py` builds them."
        )
    made = root / ASSETS
    shutil.rmtree(made, ignore_errors=True)
    made.mkdir(parents=True)
    sums = []
    for image in images:
        with image.open("rb") as unpacked:
            sums.append(
                f"{hashlib.file_digest(unpacked, 'sha256').hexdigest()}"
                f"  {image.name}\n"
            )
            unpacked.seek(0)
            with gzip.open(made / f"{image.name}.gz", "wb") as packed:
                shutil.copyfileobj(unpacked, packed)
    (made / "SHA256SUMS").write_text("".join(sums))
    shutil.copy(root / VERSIONS, made / VERSIONS.name)
    assets = sorted(ASSETS / path.name for path in made.iterdir())
    (made / NOTES).write_text(_notes(root))
    return assets


def _notes(root: Path) -> str:
    """What the release says about itself.

    🎓 It names the source of what is in the images: some of it is under the
    GPL, and whoever hands on a program under it says where its source is.
    """
    with (root / VERSIONS).open("rb") as versions:
        rows = [
            (name, pin["version"], pin["source"])
            for name, pin in tomllib.load(versions).items()
        ]
    return (
        "🧦 The firmware images socpuppet fetches the first time each is "
        f"needed, built from {_repository_url(root)}/commit/{_commit(root)}.\n"
        "\n"
        "Each image is gzipped on its own. `SHA256SUMS` has the sums of the "
        "images unpacked, so `gunzip *.gz && sha256sum -c SHA256SUMS` checks "
        "them.\n"
        "\n"
        + generated.markdown_table(("Upstream", "Version", "Source"), rows)
        + "\n"
    )


def pin(root: Path) -> str:
    """What python/socpuppet/images_release.py holds, for this repository."""
    repository = _repository_url(root)
    return (
        '"""The release of the firmware images this socpuppet asks for.\n'
        "\n"
        "Generated by tools/released_images.py from the firmware's sources: "
        "`uv run\npython tools/lint.py --fix` writes it again.\n"
        '"""\n'
        "\n"
        "#: Where the sources are, and how the images can be built.\n"
        f'REPOSITORY = "{repository}"\n'
        "#: The release's tag, which is named for the sources.\n"
        f'TAG = "{tag(root)}"\n'
        "#: Where the release's files are.\n"
        'URL = f"{REPOSITORY}/releases/download/{TAG}"\n'
    )


def _sources(root: Path) -> list[str]:
    """What the firmware is built from: its cache keys' files, in order."""
    keys = FIRMWARE_KEY.findall((root / WORKFLOW).read_text())
    hashes = [re.search(r"hashFiles\(([^)]*)\)", key) for key in keys]
    if not keys or not all(hashes):
        sys.exit(
            f"Each firmware-* cache key in {root / WORKFLOW} needs a "
            "hashFiles(), and that file has to have them: they say what the "
            "images are built from. Give each firmware job back its key."
        )
    files = _files(root)
    return sorted(
        {
            name
            for found in hashes
            if found
            for name in _hashed_by(re.findall(r"'([^']+)'", found[1]), files)
        }
    )


def _hashed_by(patterns: list[str], files: list[str]) -> set[str]:
    """The files a hashFiles() takes: `!` leaves out what came before it.

    💡 fnmatch's `*` crosses a `/` and GitHub's does not, which none of the
    keys' patterns depends on.
    """
    taken: set[str] = set()
    for pattern in patterns:
        if pattern.startswith("!"):
            taken -= set(fnmatch.filter(files, pattern[1:]))
        else:
            taken |= set(fnmatch.filter(files, pattern))
    return taken


def _files(root: Path) -> list[str]:
    """Every file git has or would add, from the top of the repository."""
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return [f for f in listing.stdout.split("\0") if (root / f).is_file()]


def _repository_url(root: Path) -> str:
    """Where this repository is on the web, as pyproject.toml says."""
    with (root / "pyproject.toml").open("rb") as pyproject:
        return str(tomllib.load(pyproject)["project"]["urls"]["Repository"])


def _commit(root: Path) -> str:
    """The commit the repository is at."""
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
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
