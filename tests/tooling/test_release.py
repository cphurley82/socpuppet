"""tools/release.py: a release of socpuppet, checked before it is built.

The tool runs for real in a throwaway repository, with a web server of the
test's own standing for GitHub's release of the images and for PyPI.
"""

import contextlib
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
#: The repository the throwaway one stands for, as GitHub names it.
GITHUB_REPOSITORY = "spam/eggs"
#: Where a test's fakes for uv and gh are, in its repository and out of git.
FAKES = "fakes"


@pytest.fixture
def web(tmp_path_factory):
    """A web server, serving what a test puts in its directory.

    web.url is where it is; web.put(path, text) publishes a file there, and
    web.looked(path) is an event set when it is first asked for.
    """
    root = tmp_path_factory.mktemp("web")
    asked = {}

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            super().do_GET()
            asked.setdefault(self.path.lstrip("/"), threading.Event()).set()

        def log_message(self, *args):
            pass

    handler = functools.partial(Handler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    class Web:
        url = f"http://127.0.0.1:{server.server_address[1]}"

        @staticmethod
        def put(path, text=""):
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(text)

        @staticmethod
        def looked(path):
            """An event set when `path` is first asked for."""
            return asked.setdefault(path, threading.Event())

    yield Web
    server.shutdown()


@pytest.fixture
def project(repo, git, web):
    """socpuppet 0.1.0 at a commit on main, its images published."""
    pin_images(repo, web, IMAGES)
    version_on_main(repo, git, "0.1.0")
    web.put(f"releases/download/{IMAGES}/SHA256SUMS", "spam  eggs.elf\n")
    return repo


def release(
    repo, web, *arguments, tag=None, branch=None, repository=GITHUB_REPOSITORY
):
    """Run the tool; `tag` or `branch` makes it a run of CI on that ref.

    The run is of `repository`. The fakes for uv and gh, when a test has
    them, are first on its PATH.
    """
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("GITHUB_")
    }
    if tag or branch:
        environment |= {
            "GITHUB_REF_TYPE": "tag" if tag else "branch",
            "GITHUB_REF_NAME": tag or branch,
            "GITHUB_REPOSITORY": repository,
        }
    return subprocess.run(
        [sys.executable, str(TOOL), *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
        env={
            **environment,
            "PATH": f"{repo / FAKES}{os.pathsep}{os.environ['PATH']}",
            "SOCPUPPET_PYPI_URL": web.url,
        },
    )


@pytest.fixture
def fakes(project):
    """uv and gh, each keeping what it was asked; gh has no release yet.

    fakes.asked(program, what) is what each was asked, a line each time.
    """
    home = project / FAKES
    home.mkdir()
    with (project / ".git" / "info" / "exclude").open("a") as exclude:
        exclude.write(f"/{FAKES}/\n")
    for program in ("uv", "gh"):
        (home / program).write_text(
            f"""#!/bin/sh
echo "$*" >> {home}/{program}.asked
case "$2" in
  view) cat {home}/release 2>/dev/null || exit 1 ;;
esac
"""
        )
        (home / program).chmod(0o755)

    class Fakes:
        @staticmethod
        def asked(program, what=""):
            """What `program` was asked that starts with `what`."""
            asked = home / f"{program}.asked"
            lines = asked.read_text().splitlines() if asked.exists() else []
            return [line for line in lines if line.startswith(what)]

        @staticmethod
        def release_is(draft):
            (home / "release").write_text(f"{str(draft).lower()}\n")

    return Fakes


@pytest.fixture
def built(project):
    """The distributions of socpuppet 0.1.0, as the wheel jobs leave them."""
    return build(
        project,
        "socpuppet-0.1.0-cp313-cp313-macosx_13_3_arm64.whl",
        "socpuppet-0.1.0-cp313-cp313-manylinux_2_28_x86_64.whl",
        "socpuppet-0.1.0.tar.gz",
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


class TestPublishingToPyPI:
    def test_on_a_tag_of_this_repository_uv_publishes_every_distribution(
        self, project, git, web, fakes, built
    ):
        git("tag", "-a", "v0.1.0", "-m", "The first release")

        result = release(project, web, "pypi", tag="v0.1.0")

        assert result.returncode == 0, result.stdout + result.stderr
        (asked,) = fakes.asked("uv", "publish ")
        assert set(built) <= set(asked.split())
        assert "--trusted-publishing always" in asked

    def test_on_a_tag_uv_asks_pypis_index_what_it_has_before_each_upload(
        self, project, git, web, fakes, built
    ):
        # A run is made again from where it failed, and PyPI keeps a file
        # once.
        git("tag", "-a", "v0.1.0", "-m", "The first release")

        release(project, web, "pypi", tag="v0.1.0")

        (asked,) = fakes.asked("uv", "publish ")
        assert f"--check-url {web.url}/simple/" in asked

    @pytest.mark.parametrize(
        "where",
        [
            {},
            {"branch": "main"},
            {"tag": "v0.1.0", "repository": "eggs/spam"},
        ],
        ids=["here", "a branch", "a fork"],
    )
    def test_anywhere_else_it_says_what_it_would_publish_and_publishes_nothing(
        self, project, git, web, fakes, built, where
    ):
        git("tag", "-a", "v0.1.0", "-m", "The first release")

        result = release(project, web, "pypi", **where)

        assert result.returncode == 0, result.stdout + result.stderr
        assert fakes.asked("uv") == []
        for name in built:
            assert Path(name).name in result.stdout

    def test_with_nothing_built_it_stops_saying_how_to_build_it(
        self, project, git, web, fakes
    ):
        git("tag", "-a", "v0.1.0", "-m", "The first release")

        result = release(project, web, "pypi", tag="v0.1.0")

        assert result.returncode != 0
        assert "tools/ci.py wheel" in result.stderr
        assert fakes.asked("uv") == []


class TestTheGitHubRelease:
    def test_on_a_tag_it_is_made_from_the_tag_with_every_distribution(
        self, project, git, web, fakes, built
    ):
        git("tag", "-a", "v0.1.0", "-m", "The first release")

        result = release(project, web, "github", tag="v0.1.0")

        assert result.returncode == 0, result.stdout + result.stderr
        (created,) = fakes.asked("gh", "release create v0.1.0 ")
        assert "--verify-tag" in created
        assert "--notes-from-tag" in created
        assert set(built) <= set(created.split())

    def test_of_a_release_is_the_projects_latest(
        self, project, git, web, fakes, built
    ):
        git("tag", "-a", "v0.1.0", "-m", "The first release")

        release(project, web, "github", tag="v0.1.0")

        (created,) = fakes.asked("gh", "release create")
        assert "--latest" in created.split()
        assert "--prerelease" not in created

    def test_of_a_release_candidate_is_a_prerelease_and_not_the_latest(
        self, project, git, web, fakes
    ):
        version_on_main(project, git, "0.1.0rc1")
        git("tag", "-a", "v0.1.0rc1", "-m", "A rehearsal")
        build(project, "socpuppet-0.1.0rc1.tar.gz")

        release(project, web, "github", tag="v0.1.0rc1")

        (created,) = fakes.asked("gh", "release create")
        assert "--prerelease" in created
        assert "--latest" not in created.split()

    def test_one_already_published_is_left_as_it_was(
        self, project, git, web, fakes, built
    ):
        git("tag", "-a", "v0.1.0", "-m", "The first release")
        fakes.release_is(draft=False)

        result = release(project, web, "github", tag="v0.1.0")

        assert result.returncode == 0
        assert fakes.asked("gh") == fakes.asked("gh", "release view ")

    def test_a_draft_a_stopped_run_left_is_deleted_and_made_again(
        self, project, git, web, fakes, built
    ):
        git("tag", "-a", "v0.1.0", "-m", "The first release")
        fakes.release_is(draft=True)

        release(project, web, "github", tag="v0.1.0")

        asked = fakes.asked("gh")
        (deleted,) = fakes.asked("gh", "release delete v0.1.0")
        (created,) = fakes.asked("gh", "release create v0.1.0")
        assert asked.index(deleted) < asked.index(created)

    def test_off_a_tag_it_says_what_it_would_make_and_makes_nothing(
        self, project, web, fakes, built
    ):
        result = release(project, web, "github")

        assert result.returncode == 0, result.stdout + result.stderr
        assert fakes.asked("gh") == []
        assert "v0.1.0" in result.stdout


class TestWaitingForPyPI:
    def test_when_pypi_lists_the_version_it_is_done(self, project, web):
        listed(web, "socpuppet-0.1.0.tar.gz", "socpuppet-0.1.0-cp313-spam.whl")

        result = release(project, web, "wait")

        assert result.returncode == 0, result.stdout + result.stderr

    def test_on_a_tag_it_looks_again_until_pypi_lists_it(
        self, project, git, web
    ):
        git("tag", "-a", "v0.1.0", "-m", "The first release")

        with listed_after_the_first_look(
            web, "socpuppet-0.1.0.tar.gz", "socpuppet-0.1.0-cp313-spam.whl"
        ):
            result = release(project, web, "wait", tag="v0.1.0")

        assert result.returncode == 0, result.stdout + result.stderr

    def test_a_version_with_only_its_source_listed_is_not_there_yet(
        self, project, web
    ):
        # pip on a machine with no compiler needs the wheel.
        listed(web, "socpuppet-0.1.0.tar.gz")

        result = release(project, web, "wait")

        assert result.returncode != 0
        assert "0.1.0" in result.stderr

    def test_here_a_version_pypi_does_not_list_fails_at_once_naming_it_and_the_index(
        self, project, web
    ):
        listed(web, "socpuppet-0.0.9.tar.gz", "socpuppet-0.0.9-cp313-spam.whl")

        result = release(project, web, "wait")

        assert result.returncode != 0
        assert "0.1.0" in result.stderr
        assert f"{web.url}/simple/socpuppet/" in result.stderr


def build(project, *names):
    """Leave distributions in the wheelhouse; returns their paths."""
    wheelhouse = project / "build" / "wheelhouse"
    wheelhouse.mkdir(parents=True)
    for name in names:
        (wheelhouse / name).write_text("spam")
    return [f"build/wheelhouse/{name}" for name in names]


@contextlib.contextmanager
def listed_after_the_first_look(web, *files):
    """PyPI's index lists the files once the tool has looked once."""
    looked = web.looked("simple/socpuppet/")
    later = threading.Thread(
        target=lambda: (looked.wait(timeout=60), listed(web, *files))
    )
    later.start()
    try:
        yield
    finally:
        later.join()


def listed(web, *files):
    """PyPI's simple index lists these files of socpuppet's."""
    web.put(
        "simple/socpuppet/index.html",
        "".join(f'<a href="../../files/{name}">{name}</a>\n' for name in files),
    )


def pin_images(repo, web, images):
    """Pin the release of the images an installed wheel would fetch."""
    (repo / PIN).parent.mkdir(parents=True, exist_ok=True)
    (repo / PIN).write_text(f'URL = "{web.url}/releases/download/{images}"\n')


def version_on_main(repo, git, version):
    """Commit socpuppet at `version`, on main as origin has it."""
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "socpuppet"\nversion = "{version}"\n'
        "[project.urls]\n"
        f'Repository = "https://example.com/{GITHUB_REPOSITORY}"\n'
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
