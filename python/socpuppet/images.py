"""🧦 Where a firmware image is: the build directory, or the cache.

A firmware image is a program built for a board, by file name:
`hello_world_socpuppet_host.elf`, `linux.bin`. There are two places to find
one.

The build directory is where `firmware/build.py` builds them: `build/firmware`
in a checkout of socpuppet, or the directory SOCPUPPET_FIRMWARE_DIR names. An
image missing from it has yet to be built.

The cache is where an installed socpuppet, which has no build directory, keeps
them: a directory in the user's cache for each release of the images, which
SOCPUPPET_CACHE_DIR moves. An image missing from it is fetched the first time
it is asked for, from the release this socpuppet pins (`images_release`), or
from a mirror of it that SOCPUPPET_IMAGES_URL names, and is checked against
the sums that release lists.

    platform.load_elf(images.find("hello_world_socpuppet_host.elf"), via=...)
"""

import fcntl
import fnmatch
import gzip
import hashlib
import http.client
import os
import pathlib
import re
import shutil
import sys
import urllib.error
import urllib.request
import zlib
from typing import IO, cast

import platformdirs

from socpuppet.images_release import REPOSITORY, TAG, URL

#: Where `firmware/build.py` builds, from the top of a checkout, and the
#: script itself, which is what makes it a checkout of socpuppet and not
#: another project with a directory of the same name.
_BUILD_DIRECTORY = pathlib.Path("build/firmware")
_BUILD_SCRIPT = pathlib.Path("firmware/build.py")
#: What builds an image: the parts of `firmware/build.py` to ask for, by the
#: image's file name. Linux's images need OpenSBI to boot, so they are asked
#: for together. Zephyr's are each named for the board they were built for.
_BUILT_BY = {
    "rom_*": "rom",
    "sbi_payload.*": "rom",
    "test_payload.*": "opensbi",
    "fw_jump.*": "opensbi linux",
    "linux.*": "opensbi linux",
    "rootfs.ext4": "opensbi linux",
    "initramfs.cpio": "opensbi linux",
    "uefi*": "edk2",
    "*_socpuppet_*": "zephyr",
    "*_qemu_*": "zephyr",
}


#: How long a server may say nothing, in seconds, before it is given up on.
_PATIENCE = 60
#: What a line of SHA256SUMS starts with.
_SHA256 = re.compile(r"[0-9a-f]{64}")
#: The bold cyan of a fetch's line, at a terminal.
_COLOR, _RESET = "\x1b[1;36m", "\x1b[0m"


class Unavailable(FileNotFoundError):
    """An image that could not be fetched: why, and how to build it instead."""


def directory() -> pathlib.Path:
    """Where images are looked for, unless a directory is asked for.

    The directory SOCPUPPET_FIRMWARE_DIR names, or else the build directory
    of a checkout of socpuppet here, or else the cache.
    """
    named = os.environ.get("SOCPUPPET_FIRMWARE_DIR")
    if named:
        return pathlib.Path(named)
    if _BUILD_DIRECTORY.is_dir() and _BUILD_SCRIPT.is_file():
        return _BUILD_DIRECTORY
    return _cache()


def find(name: str, within: pathlib.Path | None = None) -> pathlib.Path:
    """The image called `name`, in `within` or else in `directory()`.

    From the cache, it is fetched if it is not there yet, or else this is an
    Unavailable. From anywhere else it is a FileNotFoundError that says how
    to build it.
    """
    place = within or directory()
    image = place / name
    if image.exists():
        return image
    if place == _cache():
        _fetch(name, place)
        return image
    raise FileNotFoundError(
        f"There is no {image}. Build it with `{_build_command(name)}`, "
        "which takes a while the first time."
    )


def _fetch(name: str, place: pathlib.Path) -> None:
    """Put the image `name` in `place`, the cache, or say why it cannot be."""
    try:
        place.mkdir(parents=True, exist_ok=True)
        with (place / ".lock").open("w") as lock:
            # One at a time: a second that asks waits, and then finds it.
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not (place / name).exists():
                _download(name, place)
    except Unavailable:
        raise
    except OSError as error:
        raise _unavailable(
            name,
            f"It could not be kept in {place}: {error}. SOCPUPPET_CACHE_DIR "
            "moves the cache somewhere else.",
        ) from error


def _download(name: str, place: pathlib.Path) -> None:
    """Fetch the image `name` into `place`, whole and checked."""
    release = os.environ.get("SOCPUPPET_IMAGES_URL") or URL
    part = place / f"{name}.part"
    try:
        wanted = _sums(name, release).get(name)
        if wanted is None:
            raise _unavailable(
                name, f"Release {TAG} of the images has no {name}."
            )
        with urllib.request.urlopen(
            f"{release}/{name}.gz", timeout=_PATIENCE
        ) as response:
            _say_fetching(name, response.length or 0, release)
            # 💡 Unpacked as it arrives: what a boot reads is the image.
            with (
                gzip.GzipFile(fileobj=cast(IO[bytes], response)) as packed,
                part.open("wb") as unpacked,
            ):
                shutil.copyfileobj(packed, unpacked)
        with part.open("rb") as written:
            actual = hashlib.file_digest(written, "sha256").hexdigest()
        if actual != wanted:
            raise _unavailable(
                name,
                f"What was fetched of {name} has the SHA-256 {actual}, not "
                f"the {wanted} that release {TAG} lists, so it was not kept.",
            )
        part.replace(place / name)
    except (gzip.BadGzipFile, EOFError, zlib.error) as error:
        raise _unavailable(
            name,
            f"What was fetched of {name} is not whole gzip ({error}), so it "
            "was not kept.",
        ) from error
    except urllib.error.HTTPError as error:
        raise _unavailable(
            name, f"{error.url} answered {error.code}: {error.reason}."
        ) from error
    except (
        urllib.error.URLError,
        TimeoutError,
        ConnectionError,
        http.client.HTTPException,
    ) as error:
        raise _unavailable(
            name,
            f"{release} could not be reached ({error}). Check this machine's "
            "connection, or name a mirror of the release with "
            "SOCPUPPET_IMAGES_URL.",
        ) from error
    finally:
        part.unlink(missing_ok=True)


def _sums(name: str, release: str) -> dict[str, str]:
    """What the release lists: each image's SHA-256, by its file name.

    It is asked each time and not kept: what a server said once, such as a
    login page on a guest network, does not decide every later fetch.
    """
    url = f"{release}/SHA256SUMS"
    try:
        with urllib.request.urlopen(url, timeout=_PATIENCE) as response:
            listed = response.read().decode(errors="replace")
    except urllib.error.HTTPError as error:
        # 💡 A mirror's missing file says nothing of what main has published.
        if release != URL or error.code != http.client.NOT_FOUND:
            raise
        raise _unavailable(
            name,
            f"Release {TAG} of the images was never published: it appears "
            "when main first passes with these firmware sources.",
        ) from error
    sums = {
        image: digest
        for digest, _, image in (
            line.partition("  ") for line in listed.splitlines()
        )
        if _SHA256.fullmatch(digest)
    }
    if not sums:
        raise _unavailable(
            name,
            f"What {url} answered is not a list of sums, which a login page "
            "on a guest network would explain.",
        )
    return sums


def _say_fetching(name: str, size: int, release: str) -> None:
    """Say on standard error that a download has started, once for each."""
    line = (
        f"🧦 Fetching {name} ({size / 1_000_000:.1f} MB) from "
        f"{release.partition('://')[2]}"
    )
    if sys.stderr.isatty() and not os.environ.get("NO_COLOR"):
        line = f"{_COLOR}{line}{_RESET}"
    print(line, file=sys.stderr)


def _unavailable(name: str, what_went_wrong: str) -> Unavailable:
    """The error for an image: what went wrong, and how to build it instead."""
    return Unavailable(
        f"{what_went_wrong} To build it yourself, clone {REPOSITORY}, run "
        f"`{_build_command(name)}` there, and point SOCPUPPET_FIRMWARE_DIR "
        "at its build/firmware: docs/boot-your-firmware.md has the long form."
    )


def _cache() -> pathlib.Path:
    """Where this socpuppet's release of the images is kept."""
    cache = os.environ.get(
        "SOCPUPPET_CACHE_DIR"
    ) or platformdirs.user_cache_dir("socpuppet")
    return pathlib.Path(cache, "images", TAG)


def _build_command(name: str) -> str:
    """What builds the image `name`: everything, if it is none we know."""
    for pattern, parts in _BUILT_BY.items():
        if fnmatch.fnmatchcase(name, pattern):
            return f"uv run firmware/build.py {parts}"
    return "uv run firmware/build.py"
