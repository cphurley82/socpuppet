"""tools/release.py: a release of socpuppet, checked before it is built.

The tool runs for real in a throwaway repository, with a web server of the
test's own standing for GitHub's release of the images and for PyPI.
"""

import functools
import http.server
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
TOOL = REPOSITORY / "tools" / "release.py"
PIN = "python/socpuppet/images_release.py"
IMAGES = "images-spam"


@pytest.fixture
def web(tmp_path_factory):
    """A web server, serving what a test puts in its directory.

    web.url is where it is; web.put(path, text) publishes a file there.
    """
    root = tmp_path_factory.mktemp("web")
    handler = functools.partial(QuietHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    class Web:
        url = f"http://127.0.0.1:{server.server_address[1]}"

        @staticmethod
        def put(path, text=""):
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(text)

    yield Web
    server.shutdown()


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def project(repo, git, web):
    """socpuppet 0.1.0 at a commit on main, its images published."""
    pin_images(repo, web, IMAGES)
    version_on_main(repo, git, "0.1.0")
    web.put(f"releases/download/{IMAGES}/SHA256SUMS", "spam  eggs.elf\n")
    return repo


def release(repo, web, *arguments, tag=None):
    """Run the tool; `tag` makes it a run of CI on that tag."""
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("GITHUB_")
    }
    if tag:
        environment |= {"GITHUB_REF_TYPE": "tag", "GITHUB_REF_NAME": tag}
    return subprocess.run(
        [sys.executable, str(TOOL), *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
        env={**environment, "SOCPUPPET_PYPI_URL": web.url},
    )


class TestTheCheckOnTheTagOfARelease:
    def test_of_the_version_on_main_with_its_images_published_passes(
        self, project, git, web
    ):
        git("tag", "-a", "v0.1.0", "-m", "The first release")

        result = release(project, web, "check", tag="v0.1.0")

        assert result.returncode == 0, result.stdout + result.stderr

    def test_whose_name_is_not_v_and_the_version_is_refused_naming_both(
        self, project, git, web
    ):
        git("tag", "-a", "v0.2.0", "-m", "Too soon")

        result = release(project, web, "check", tag="v0.2.0")

        assert result.returncode == 1
        assert "v0.2.0" in refusal(result, "0.1.0")

    def test_that_is_lightweight_is_refused_saying_how_to_annotate_it(
        self, project, git, web
    ):
        git("tag", "v0.1.0")

        result = release(project, web, "check", tag="v0.1.0")

        assert result.returncode == 1
        assert refusal(result, "git tag -a")

    def test_whose_commit_is_not_on_main_is_refused(self, project, git, web):
        git("commit", "--quiet", "--allow-empty", "-m", "a branch's")
        git("tag", "-a", "v0.1.0", "-m", "From a branch")

        result = release(project, web, "check", tag="v0.1.0")

        assert result.returncode == 1
        assert refusal(result, "not on main")

    def test_with_no_main_in_the_checkout_says_how_to_fetch_it(
        self, project, git, web
    ):
        git("tag", "-a", "v0.1.0", "-m", "The first release")
        git("update-ref", "-d", "refs/remotes/origin/main")

        result = release(project, web, "check", tag="v0.1.0")

        assert result.returncode == 1
        assert refusal(result, "fetch-depth 0")

    def test_whose_images_are_not_published_is_refused_naming_their_release(
        self, project, git, web
    ):
        git("tag", "-a", "v0.1.0", "-m", "The first release")
        pin_images(project, web, "images-eggs")

        result = release(project, web, "check", tag="v0.1.0")

        assert result.returncode == 1
        assert refusal(result, "images-eggs")

    def test_of_a_version_already_on_pypi_is_refused(self, project, git, web):
        git("tag", "-a", "v0.1.0", "-m", "Again")
        web.put("pypi/socpuppet/0.1.0/json", "{}")

        result = release(project, web, "check", tag="v0.1.0")

        assert result.returncode == 1
        assert refusal(result, "PyPI")

    @pytest.mark.parametrize("version", ["0.1", "0.1.0.dev1", "0.1.0-rc1"])
    def test_of_a_version_not_x_y_z_or_a_candidate_is_refused(
        self, project, git, web, version
    ):
        version_on_main(project, git, version)
        git("tag", "-a", f"v{version}", "-m", "spam")

        result = release(project, web, "check", tag=f"v{version}")

        assert result.returncode == 1
        assert refusal(result, version)

    def test_of_a_release_candidate_passes(self, project, git, web):
        version_on_main(project, git, "0.1.0rc1")
        git("tag", "-a", "v0.1.0rc1", "-m", "A rehearsal")

        result = release(project, web, "check", tag="v0.1.0rc1")

        assert result.returncode == 0, result.stdout + result.stderr


class TestTheCheckHere:
    def test_with_no_tag_made_it_passes_saying_how_to_make_it(
        self, project, web
    ):
        result = release(project, web, "check")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "git tag -a v0.1.0" in result.stdout

    def test_it_still_refuses_images_that_are_not_published(self, project, web):
        pin_images(project, web, "images-eggs")

        result = release(project, web, "check")

        assert result.returncode == 1
        assert refusal(result, "images-eggs")

    def test_it_still_refuses_a_version_pypi_has(self, project, web):
        web.put("pypi/socpuppet/0.1.0/json", "{}")

        result = release(project, web, "check")

        assert result.returncode == 1
        assert refusal(result, "PyPI")

    def test_it_still_refuses_a_version_not_x_y_z_or_a_candidate(
        self, project, git, web
    ):
        version_on_main(project, git, "0.1")

        result = release(project, web, "check")

        assert result.returncode == 1
        assert refusal(result, "X.Y.Z")


def pin_images(repo, web, images):
    """Pin the release of the images an installed wheel would fetch."""
    (repo / PIN).parent.mkdir(parents=True, exist_ok=True)
    (repo / PIN).write_text(f'URL = "{web.url}/releases/download/{images}"\n')


def version_on_main(repo, git, version):
    """Commit socpuppet at `version`, on main as origin has it."""
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "socpuppet"\nversion = "{version}"\n'
    )
    git("add", "-A")
    git("commit", "--quiet", "-m", f"socpuppet {version}")
    git("update-ref", "refs/remotes/origin/main", "HEAD")


def refusal(result, words):
    """The line the check refused with that says `words`, or None."""
    for line in result.stdout.splitlines():
        if line.startswith("❌") and words in line:
            return line
    return None
