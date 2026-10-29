"""pytest support for tests that build a socpuppet Platform.

The SystemC kernel can be started only once per process, so a process can
hold only one Platform. Mark a test with ``@pytest.mark.platform`` and this
plugin runs it in a fresh Python process of its own.

A fresh interpreter is used rather than fork() (as pytest-forked does)
because forking is unsafe on macOS and a forked child inherits whatever
kernel state the parent already has. The cost is one pytest startup per
marked test.

Marked ``@pytest.mark.platform(scope="class")``, a class's tests share one
process instead, so that a class-scoped fixture, a board booted once, is
made once for all of them (a marked test outside a class still has one of
its own). Tests of the class with different parameters, as a parametrized
class fixture gives them, have a process for each. The first of them to run
starts the process for every one of the class that the session selected, and
each reports in its turn. Under pytest-xdist, hand the tests out with
``--dist loadscope``, which keeps a class on one worker.

A marked test that runs for longer than ``socpuppet_platform_timeout``
seconds is stopped and fails, and so is a class's process, with what it
had not finished. The limit is a setting in pytest's configuration, 900
unless set, and 0 means no limit::

    [tool.pytest.ini_options]
    socpuppet_platform_timeout = 60

pytest finds the plugin by itself where socpuppet is installed. Where the
package is imported straight from a source tree, enable it from a
``conftest.py``::

    pytest_plugins = ["socpuppet.pytest_plugin"]
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
from typing import Literal

import pytest

# Name of the environment variable that tells a child process where to write
# its test reports. A process that has it set is a child.
_REPORT_FILE_ENV = "SOCPUPPET_PYTEST_REPORT_FILE"

# pytest's own exit statuses for "all passed" and "some tests failed". Any
# other status means the process did not get to finish normally.
_FINISHED = (pytest.ExitCode.OK, pytest.ExitCode.TESTS_FAILED)

# The phases pytest reports a test in, and the ones that come before teardown.
_Phase = Literal["setup", "call", "teardown"]
_BEFORE_TEARDOWN: tuple[_Phase, ...] = ("setup", "call")


# The setting for how long a marked test may run, and what it is when
# nobody sets it. A boot to a prompt takes about 90 s on a free Intel Mac and
# more than 300 on a machine that is building besides, with a test worker on
# every core. The limit is there for a script that loops for ever, so it is
# set well past the slowest honest boot; and it is the default, not a setting
# in socpuppet's own configuration, since the wheel's tests run without that.
_TIMEOUT_SETTING = "socpuppet_platform_timeout"
_DEFAULT_TIMEOUT_SECONDS = 900.0


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add the setting for how long a `platform` test may run."""
    parser.addini(
        _TIMEOUT_SETTING,
        "How many seconds a test marked `platform` may run before it is "
        "stopped and fails. 0 means no limit.",
        default=str(_DEFAULT_TIMEOUT_SECONDS),
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the markers, and in a child, report to the parent."""
    config.addinivalue_line(
        "markers",
        "platform(scope=None): builds a Platform, so the test runs in its "
        "own process (one SystemC kernel per process); with "
        "scope='class', a class's tests share one",
    )
    report_file = os.environ.get(_REPORT_FILE_ENV)
    if report_file:
        config.pluginmanager.register(_ChildReporter(config, report_file))


def pytest_runtest_protocol(
    item: pytest.Item, nextitem: pytest.Item | None
) -> bool | None:
    """Run a `platform` test in a process of its own."""
    if not _runs_in_a_process(item):
        # Run normally, in this process: a test that is skipped whatever
        # happens needs no process to skip.
        return None

    item.ihook.pytest_runtest_logstart(
        nodeid=item.nodeid, location=item.location
    )
    for report in _reports_of(item):
        item.ihook.pytest_runtest_logreport(report=report)
    # The test's own fixtures lived and died in the child. Here, pytest still
    # has to finish with any class or module it set up for earlier tests and
    # that the next test does not share. There is no public hook for just
    # that, so this reaches into pytest's setup state; a test in
    # test_pytest_plugin.py pins the behavior.
    item.session._setupstate.teardown_exact(nextitem)
    item.ihook.pytest_runtest_logfinish(
        nodeid=item.nodeid, location=item.location
    )
    return True


# What a class's process reported for the tests of it still to report, by
# node id: the first of them to run fills it in for the rest.
_waiting = pytest.StashKey[dict[str, list[pytest.TestReport]]]()


def _reports_of(item: pytest.Item) -> list[pytest.TestReport]:
    """Run a `platform` test in a process of its own, or its class's."""
    waiting = item.config.stash.setdefault(_waiting, {})
    if item.nodeid in waiting:
        return waiting.pop(item.nodeid)
    if not _shares_its_classs_process(item):
        return _run_in_child_process([item])[item.nodeid]
    together = [
        each
        for each in item.session.items
        if _process_shared_by(each) == _process_shared_by(item)
        and _shares_its_classs_process(each)
        and _runs_in_a_process(each)
    ]
    reports = _run_in_child_process(together)
    waiting.update(reports)
    return waiting.pop(item.nodeid)


def _runs_in_a_process(item: pytest.Item) -> bool:
    """Whether a test runs in a process apart from the session's."""
    return (
        item.get_closest_marker("platform") is not None
        and item.get_closest_marker("skip") is None
        and _REPORT_FILE_ENV not in os.environ
    )


def _shares_its_classs_process(item: pytest.Item) -> bool:
    """Whether a test is of a class marked to share one process."""
    marker = item.get_closest_marker("platform")
    return (
        marker is not None
        and marker.kwargs.get("scope") == "class"
        and item.getparent(pytest.Class) is not None
    )


def _process_shared_by(item: pytest.Item) -> tuple[object, str]:
    """Which tests share a class's process: its class's, with its parameters.

    A class-scoped fixture with parameters is made once for each, and each
    would be a platform of its own, so each has a process of its own.
    """
    callspec = getattr(item, "callspec", None)
    return item.getparent(pytest.Class), callspec.id if callspec else ""


class _ChildReporter:
    """In the child: writes each test report where the parent will read it."""

    def __init__(self, config: pytest.Config, report_file: str) -> None:
        self._config = config
        self._report_file = report_file

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        data = self._config.hook.pytest_report_to_serializable(
            config=self._config, report=report
        )
        with open(self._report_file, "a") as out:
            out.write(json.dumps(data) + "\n")


def _run_in_child_process(
    items: list[pytest.Item],
) -> dict[str, list[pytest.TestReport]]:
    """Run tests in one fresh interpreter, and return each one's reports."""
    config = items[0].config
    timeout = float(config.getini(_TIMEOUT_SETTING))
    # The child's temporary directories go inside this session's. Left to
    # itself, the child would make one beside every other session's and, on
    # its way out, clear away those that are old enough: on a busy machine,
    # trees of thousands of files, for minutes, while its time runs out. The
    # child empties whatever directory it is given, so it gets a fresh one,
    # never the session's own. There is no public way to the session's
    # tmp_path_factory; pytest's own fixture reaches it the same way.
    tmp_path_factory: pytest.TempPathFactory = (
        config._tmp_path_factory  # type: ignore[attr-defined]
    )
    basetemp = tmp_path_factory.mktemp("platform")
    with tempfile.NamedTemporaryFile(mode="r", suffix=".jsonl") as report_file:
        child = subprocess.Popen(
            # A node id is relative to the rootdir, so anchor it there. The
            # child keeps our working directory, as an unmarked test would.
            [
                sys.executable,
                "-m",
                "pytest",
                "--rootdir",
                str(config.rootpath),
                "--basetemp",
                str(basetemp),
                *(str(config.rootpath / item.nodeid) for item in items),
            ],
            env={**os.environ, _REPORT_FILE_ENV: report_file.name},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = child.communicate(timeout=timeout or None)
            unfinished = (
                None
                if child.returncode in _FINISHED
                else (
                    "The test's process exited with status "
                    f"{describe_exit_status(child.returncode)} instead of "
                    "finishing."
                )
            )
        except subprocess.TimeoutExpired:
            stdout, stderr = _stop(child)
            unfinished = (
                f"The test ran for longer than {_seconds(timeout)} and was "
                "stopped. A script or a firmware that loops for ever is the "
                "usual cause. If the test needs longer, raise "
                f"{_TIMEOUT_SETTING} in pytest's configuration."
            )
        output = stdout + stderr
        reports: dict[str, list[pytest.TestReport]] = {
            item.nodeid: [] for item in items
        }
        for line in report_file:
            report = _report_from_json(config, line)
            reports[report.nodeid].append(report)
    if unfinished is not None:
        # Each test that did not get as far as its teardown was cut short.
        # If every one did, the process died on its way out, after the last.
        cut_short = [
            item
            for item in items
            if "teardown" not in {r.when for r in reports[item.nodeid]}
        ] or items[-1:]
        # The first was the one running; the rest never started.
        first, *never_started = cut_short
        reports[first.nodeid].append(
            _unfinished_report(
                first,
                f"{unfinished} Its output follows.\n\n{output}",
                phases_reported={r.when for r in reports[first.nodeid]},
            )
        )
        for item in never_started:
            reports[item.nodeid].append(
                _unfinished_report(
                    item,
                    "Never ran: the class's process died during "
                    f"{first.nodeid}.",
                    phases_reported=set(),
                )
            )
    return reports


def _report_from_json(config: pytest.Config, line: str) -> pytest.TestReport:
    """A report the child wrote, as pytest gave it there.

    ⚠️ A skip's reason is a tuple of where and why, which JSON brings back
    as a list, and pytest's summary of skips takes only a tuple.
    """
    data = json.loads(line)
    if data.get("outcome") == "skipped" and isinstance(data["longrepr"], list):
        data["longrepr"] = tuple(data["longrepr"])
    report: pytest.TestReport = config.hook.pytest_report_from_serializable(
        config=config, data=data
    )
    return report


def _unfinished_report(
    item: pytest.Item, why: str, phases_reported: set[str]
) -> pytest.TestReport:
    """A failed report for a child process that did not finish its test."""
    # Blame the first phase that never reported, so the test is counted once.
    # If every phase reported, the process died afterwards, on the way out.
    when: _Phase = next(
        (phase for phase in _BEFORE_TEARDOWN if phase not in phases_reported),
        "teardown",
    )
    return pytest.TestReport(
        nodeid=item.nodeid,
        location=item.location,
        # As pytest's own reports have them: a name to 1, since a Mark is
        # more than xdist can send between processes.
        keywords=dict.fromkeys(item.keywords, 1),
        outcome="failed",
        longrepr=why,
        when=when,
    )


def describe_exit_status(returncode: int) -> str:
    """An exit status for a person: with the signal's name if it was one."""
    if returncode < 0:
        try:
            return f"{returncode} ({signal.Signals(-returncode).name})"
        except ValueError:
            # A signal Python has no name for: most of Linux's real-time
            # signals, for one.
            pass
    return str(returncode)


def _seconds(seconds: float) -> str:
    return f"{seconds:g} second{'' if seconds == 1 else 's'}"


# How long a child that was told to stop gets to say where it was.
_LAST_WORDS_SECONDS = 5


def _stop(child: subprocess.Popen[str]) -> tuple[str, str]:
    """Stop a child that ran out of time, and return what it wrote."""
    # Aborted, and not simply killed: pytest's fault handler answers the
    # abort signal by writing where Python was, as far as it can tell. (A
    # script runs on a SystemC thread's stack, where it often cannot.) A
    # child too far gone to answer is killed.
    child.send_signal(signal.SIGABRT)
    try:
        return child.communicate(timeout=_LAST_WORDS_SECONDS)
    except subprocess.TimeoutExpired:
        child.kill()
        return child.communicate()
