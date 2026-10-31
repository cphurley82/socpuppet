"""tools/released_images.py: which release of the images this source asks for."""

import gzip
import hashlib
import os
import re
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
TOOL = REPOSITORY / "tools" / "released_images.py"
PIN = "python/socpuppet/images_release.py"

#: Two of the firmware's cache keys, as `.github/workflows/firmware.yml`
#: writes them, with a key that is not the firmware's beside them.
WORKFLOW = """\
    jobs:
      fetch-sdk:
        steps:
          - with:
              key: sdk-${{ hashFiles('not-firmware/spam') }}
      firmware-rom:
        steps:
          - with:
              key: firmware-rom-${{ hashFiles('firmware/rom/**', 'firmware/versions.toml') }}
      firmware-zephyr:
        steps:
          - with:
              key: firmware-zephyr-${{ hashFiles('firmware/**', '!firmware/twister*', 'zephyr_module/**') }}
"""


@pytest.fixture
def sources(repo):
    """A repository with a firmware workflow and a file for each kind of key."""
    (repo / ".github/workflows").mkdir(parents=True)
    (repo / ".github/workflows/firmware.yml").write_text(
        textwrap.dedent(WORKFLOW)
    )
    (repo / "pyproject.toml").write_text(
        '[project.urls]\nRepository = "https://example.com/spam/eggs"\n'
    )
    for name in (
        "firmware/versions.toml",
        "firmware/rom/start.S",
        "firmware/twister-requirements.txt",
        "zephyr_module/board.dts",
        "not-firmware/spam",
    ):
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("spam\n")
    return repo


def released_images(repo, *arguments, **environment):
    return subprocess.run(
        [sys.executable, str(TOOL), *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
        # A run of CI on main is what a test asks for, and never what it is
        # handed by whatever it is run from.
        env={
            **os.environ,
            "GITHUB_REF_NAME": "",
            "GITHUB_REPOSITORY": "",
            **environment,
        },
    )


def tag_of(repo):
    result = released_images(repo, "tag")
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


class TestTheTag:
    def test_is_the_word_images_and_twelve_hex_digits(self, sources):
        assert re.fullmatch(r"images-[0-9a-f]{12}", tag_of(sources))

    def test_of_the_same_sources_is_the_same_tag(self, sources):
        assert tag_of(sources) == tag_of(sources)

    @pytest.mark.parametrize(
        "source",
        [
            "firmware/versions.toml",
            "firmware/rom/start.S",
            "zephyr_module/board.dts",
        ],
    )
    def test_changes_with_a_byte_of_a_file_a_firmware_key_hashes(
        self, sources, source
    ):
        before = tag_of(sources)

        (sources / source).write_text("eggs\n")

        assert tag_of(sources) != before

    def test_changes_when_a_source_is_renamed(self, sources):
        before = tag_of(sources)

        (sources / "firmware/rom/start.S").rename(
            sources / "firmware/rom/begin.S"
        )

        assert tag_of(sources) != before

    @pytest.mark.parametrize(
        "other",
        [
            # Left out of the one key that would take it.
            "firmware/twister-requirements.txt",
            # Hashed by a key that is not the firmware's.
            "not-firmware/spam",
        ],
    )
    def test_stays_when_a_file_no_firmware_key_hashes_changes(
        self, sources, other
    ):
        before = tag_of(sources)

        (sources / other).write_text("eggs\n")

        assert tag_of(sources) == before

    def test_ignores_a_file_git_is_told_to_ignore(self, sources):
        before = tag_of(sources)
        (sources / ".gitignore").write_text("*.o\n")

        (sources / "firmware/rom/start.o").write_text("built\n")

        assert tag_of(sources) == before

    def test_of_a_workflow_with_no_firmware_keys_is_refused_saying_so(
        self, sources
    ):
        (sources / ".github/workflows/firmware.yml").write_text("jobs:\n")

        result = released_images(sources, "tag")

        assert result.returncode != 0
        assert "firmware.yml" in result.stderr
        assert "firmware-" in result.stderr

    def test_of_a_workflow_with_a_firmware_key_it_cannot_read_is_refused(
        self, sources
    ):
        workflow = sources / ".github/workflows/firmware.yml"
        workflow.write_text(
            workflow.read_text()
            + "              key: firmware-spam-${{ runner.os }}\n"
        )

        result = released_images(sources, "tag")

        assert result.returncode != 0
        assert "hashFiles" in result.stderr

    def test_reads_a_key_that_names_the_runner_before_its_hash(self, sources):
        workflow = sources / ".github/workflows/firmware.yml"
        workflow.write_text(
            workflow.read_text().replace(
                "firmware-rom-${{ hashFiles",
                "firmware-rom-${{ runner.os }}-${{ hashFiles",
            )
        )
        before = tag_of(sources)

        (sources / "firmware/versions.toml").write_text("eggs\n")

        assert tag_of(sources) != before


class TestThePin:
    def test_written_names_the_tag_and_where_its_release_is(self, sources):
        released_images(sources, "write", PIN)

        pin = run_as_python(sources / PIN)
        assert pin["TAG"] == tag_of(sources)
        assert (
            pin["URL"]
            == f"https://example.com/spam/eggs/releases/download/{pin['TAG']}"
        )

    def test_just_written_passes_the_check(self, sources):
        released_images(sources, "write", PIN)

        assert released_images(sources, "check", PIN).returncode == 0

    def test_of_other_sources_fails_the_check_and_says_how_to_write_it(
        self, sources
    ):
        released_images(sources, "write", PIN)
        (sources / "firmware/versions.toml").write_text("eggs\n")

        result = released_images(sources, "check", PIN)

        assert result.returncode != 0
        assert PIN in result.stdout
        assert "tools/lint.py --fix" in result.stdout

    def test_that_is_stale_fails_lint_and_names_the_file(self, sources, lint):
        (sources / PIN).parent.mkdir(parents=True)
        (sources / PIN).write_text('TAG = "images-stale"\n')

        result = lint("released-images")

        assert "❌ released-images" in result.stdout
        assert PIN in result.stdout

    def test_that_is_stale_is_written_again_by_lint_fix(self, sources, lint):
        (sources / PIN).parent.mkdir(parents=True)
        (sources / PIN).write_text('TAG = "images-stale"\n')

        lint("--fix", "released-images")

        assert lint("released-images").returncode == 0


#: Two images, as the firmware jobs hand them on, in build/firmware.
SPAM_ELF = b"\x7fELF spam" * 1000
LINUX_BIN = b"a kernel" * 1000
#: What the sources' firmware/versions.toml says of its upstreams.
VERSIONS = """\
[linux]
version = "6.18.57"
source = "https://example.com/linux"
sha256 = "abcdef"

[dropbear]
version = "2026.91-r0"
source = "https://example.com/dropbear"
"""


@pytest.fixture
def built(sources, git):
    """The sources, committed, with their images built and more besides."""
    (sources / "firmware/versions.toml").write_text(VERSIONS)
    (sources / ".gitignore").write_text("build\n")
    git("add", "-A")
    git(
        *("-c", "user.name=Spam", "-c", "user.email=spam@example.com"),
        *("commit", "--quiet", "-m", "Spam"),
    )
    firmware = sources / "build/firmware"
    firmware.mkdir(parents=True)
    (firmware / "spam_socpuppet_host.elf").write_bytes(SPAM_ELF)
    (firmware / "linux.bin").write_bytes(LINUX_BIN)
    (firmware / "build_spam.log").write_text("Built spam.\n")
    (firmware / "linux-x86_64").mkdir()
    (firmware / "linux-x86_64/tool.bin").write_text("for this machine alone\n")
    return sources


@pytest.fixture
def gh(tmp_path_factory):
    """A `gh` that keeps what it was asked, on a PATH of its own.

    It has no release until a test says so.
    """
    home = tmp_path_factory.mktemp("gh")
    program = home / "gh"
    program.write_text(
        f"""#!/bin/sh
echo "$*" >> {home}/asked
case "$2" in
  view) cat {home}/release ;;
  create) test ! -e {home}/broken ;;
esac
"""
    )
    program.chmod(0o755)
    return home


def a_release_is_published(gh):
    (gh / "release").write_text("false\n")


def a_stopped_run_left_a_draft(gh):
    (gh / "release").write_text("true\n")


def making_a_release_will_fail(gh):
    (gh / "broken").touch()


def gh_was_asked(gh, what):
    """Each thing `gh` was asked of the kind `what`: `release create`, say."""
    asked = gh / "asked"
    lines = asked.read_text().splitlines() if asked.exists() else []
    return [line for line in lines if line.startswith(what)]


def on_main(gh):
    """What a run on this repository's main has, with `gh` on its PATH."""
    return {
        "GITHUB_REF_NAME": "main",
        "GITHUB_REPOSITORY": "spam/eggs",
        "PATH": f"{gh}{os.pathsep}{os.environ['PATH']}",
    }


def commit_of(repo):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class TestWhatIsMadeForARelease:
    def test_each_image_is_gzipped_and_unpacks_to_the_same_bytes(self, built):
        released_images(built, "publish")

        assets = built / "build/images"
        assert (
            gzip.decompress(
                (assets / "spam_socpuppet_host.elf.gz").read_bytes()
            )
            == SPAM_ELF
        )
        assert (
            gzip.decompress((assets / "linux.bin.gz").read_bytes()) == LINUX_BIN
        )

    def test_an_image_is_smaller_gzipped_when_it_can_be(self, built):
        released_images(built, "publish")

        assert (built / "build/images/linux.bin.gz").stat().st_size < len(
            LINUX_BIN
        )

    def test_the_sums_are_of_the_images_unpacked_as_sha256sum_writes_them(
        self, built
    ):
        released_images(built, "publish")

        sums = (built / "build/images/SHA256SUMS").read_text().splitlines()
        assert sorted(sums) == sorted(
            [
                f"{hashlib.sha256(SPAM_ELF).hexdigest()}  "
                "spam_socpuppet_host.elf",
                f"{hashlib.sha256(LINUX_BIN).hexdigest()}  linux.bin",
            ]
        )

    @pytest.mark.parametrize(
        "kind",
        [
            "uefi.fd",
            "uefi_shell.efi",
            "rootfs.ext4",
            "initramfs.cpio",
            "linux.map",
        ],
    )
    def test_every_kind_of_image_the_firmware_jobs_hand_on_is_made(
        self, built, kind
    ):
        (built / "build/firmware" / kind).write_bytes(b"spam")

        released_images(built, "publish")

        assert (built / "build/images" / f"{kind}.gz").exists()

    @pytest.mark.parametrize("other", ["build_spam.log", "tool.bin"])
    def test_a_log_of_the_build_or_a_tree_it_was_built_in_is_left_out(
        self, built, other
    ):
        released_images(built, "publish")

        assert not (built / "build/images" / f"{other}.gz").exists()

    def test_the_versions_the_images_were_built_from_go_with_them(self, built):
        released_images(built, "publish")

        assert (built / "build/images/versions.toml").read_text() == VERSIONS

    def test_the_notes_name_the_commit_and_each_upstreams_version_and_source(
        self, built
    ):
        released_images(built, "publish")

        notes = (built / "build/images/NOTES.md").read_text()
        assert commit_of(built) in notes
        for said in (
            "6.18.57",
            "https://example.com/linux",
            "2026.91-r0",
            "https://example.com/dropbear",
        ):
            assert said in notes

    def test_what_an_earlier_run_made_is_not_kept(self, built):
        released_images(built, "publish")
        (built / "build/firmware/linux.bin").unlink()

        released_images(built, "publish")

        assert not (built / "build/images/linux.bin.gz").exists()

    def test_with_no_images_built_it_stops_and_says_how_to_build_them(
        self, sources
    ):
        result = released_images(sources, "publish")

        assert result.returncode != 0
        assert "firmware/build.py" in result.stderr


class TestWhoPublishes:
    def test_a_run_on_main_publishes_every_file_at_this_commit(self, built, gh):
        result = released_images(built, "publish", **on_main(gh))

        assert result.returncode == 0, result.stderr
        [create] = gh_was_asked(gh, "release create")
        assert create.startswith(f"release create {tag_of(built)} ")
        assert f"--target {commit_of(built)}" in create
        assert set(create.split()) >= {
            "build/images/linux.bin.gz",
            "build/images/spam_socpuppet_host.elf.gz",
            "build/images/SHA256SUMS",
            "build/images/versions.toml",
        }

    def test_the_notes_are_what_the_release_says_and_not_one_of_its_files(
        self, built, gh
    ):
        released_images(built, "publish", **on_main(gh))

        [create] = gh_was_asked(gh, "release create")
        assert create.count("build/images/NOTES.md") == 1
        assert "--notes-file build/images/NOTES.md" in create

    def test_the_release_is_never_marked_the_repositorys_latest(
        self, built, gh
    ):
        released_images(built, "publish", **on_main(gh))

        [create] = gh_was_asked(gh, "release create")
        assert "--latest=false" in create

    def test_a_release_already_there_is_left_alone_and_said_to_be(
        self, built, gh
    ):
        # 💡 Images are not built the same twice, so the first build stays.
        a_release_is_published(gh)

        result = released_images(built, "publish", **on_main(gh))

        assert result.returncode == 0, result.stderr
        assert gh_was_asked(gh, "release create") == []
        assert gh_was_asked(gh, "release delete") == []
        assert tag_of(built) in result.stdout

    def test_a_draft_a_stopped_run_left_is_replaced_by_the_release(
        self, built, gh
    ):
        a_stopped_run_left_a_draft(gh)

        result = released_images(built, "publish", **on_main(gh))

        assert result.returncode == 0, result.stderr
        assert len(gh_was_asked(gh, f"release delete {tag_of(built)}")) == 1
        assert len(gh_was_asked(gh, f"release create {tag_of(built)}")) == 1

    def test_the_run_fails_in_a_line_that_says_what_to_do_when_it_cannot_publish(
        self, built, gh
    ):
        making_a_release_will_fail(gh)

        result = released_images(built, "publish", **on_main(gh))

        assert result.returncode != 0
        assert "run this job again" in result.stderr
        assert "Traceback" not in result.stderr

    @pytest.mark.parametrize(
        "elsewhere",
        [
            {"GITHUB_REF_NAME": "spam"},
            {"GITHUB_REF_NAME": ""},
            {"GITHUB_REPOSITORY": "a-fork/eggs"},
            {"GITHUB_REPOSITORY": ""},
        ],
        ids=["another_branch", "not_in_ci", "a_fork", "no_repository"],
    )
    def test_any_other_run_says_what_it_would_publish_and_publishes_nothing(
        self, built, gh, elsewhere
    ):
        result = released_images(
            built, "publish", **{**on_main(gh), **elsewhere}
        )

        assert result.returncode == 0, result.stderr
        assert gh_was_asked(gh, "") == []
        assert tag_of(built) in result.stdout
        assert "linux.bin.gz" in result.stdout


class TestThisRepository:
    def test_each_upstream_says_where_its_source_is(self):
        with (REPOSITORY / "firmware/versions.toml").open("rb") as versions:
            pins = tomllib.load(versions)

        assert pins
        for name, pin in pins.items():
            assert pin.get("source", "").startswith("https://"), name

    def test_its_tag_is_the_one_its_package_asks_for(self):
        pin = run_as_python(REPOSITORY / PIN)

        assert pin["TAG"] == tag_of(REPOSITORY)

    def test_each_job_that_builds_firmware_has_a_key_the_tag_is_made_from(self):
        workflow = (REPOSITORY / ".github/workflows/firmware.yml").read_text()
        jobs = re.findall(r"^  (firmware-[\w-]+):$", workflow, re.MULTILINE)

        assert jobs
        for job in jobs:
            assert f"key: {job}-" in workflow


def run_as_python(path: Path) -> dict[str, str]:
    """What a generated module defines, without importing the package."""
    defined: dict[str, str] = {}
    exec(path.read_text(), defined)
    return defined
