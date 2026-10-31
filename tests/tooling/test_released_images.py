"""tools/released_images.py: which release of the images this source asks for."""

import re
import subprocess
import sys
import textwrap
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


def released_images(repo, *arguments):
    return subprocess.run(
        [sys.executable, str(TOOL), *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
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


class TestThisRepository:
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
