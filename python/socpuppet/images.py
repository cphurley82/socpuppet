"""🧦 Where a firmware image is: the build directory, or the cache.

A firmware image is a program built for a board, by file name:
`hello_world_socpuppet_host.elf`, `linux.bin`. There are two places to find
one.

The build directory is where `firmware/build.py` builds them: `build/firmware`
in a checkout of socpuppet, or the directory SOCPUPPET_FIRMWARE_DIR names. An
image missing from it has yet to be built.

The cache is where an installed socpuppet, which has no build directory, keeps
them: a directory in the user's cache for each release of the images, which
SOCPUPPET_CACHE_DIR moves.

    platform.load_elf(images.find("hello_world_socpuppet_host.elf"), via=...)
"""

import fnmatch
import os
import pathlib

import platformdirs

from socpuppet.images_release import TAG

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

    Or else a FileNotFoundError that says how to build it.
    """
    image = (within or directory()) / name
    if not image.exists():
        raise FileNotFoundError(
            f"There is no {image}. Build it with `{_build_command(name)}`, "
            "which takes a while the first time."
        )
    return image


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
