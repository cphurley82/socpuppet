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
starts the process for every one of the class that the session selected with
the same parameters, and each reports in its turn. Under pytest-xdist, hand
the tests out with ``--dist loadgroup``: the plugin makes a group of the
tests that share a process, which goes to one worker, and the rest are
handed out one at a time. (``--dist loadscope`` works too, but keeps every
class on one worker, so that a class whose tests each boot boots them one
after another.) Handed out xdist's default way, ``--dist load``, or with
``worksteal``, a class's tests would reach several workers and each would
boot it again, so they fail at setup instead and say so.

A marked test that runs for longer than ``socpuppet_platform_timeout``
seconds is stopped and fails, and in a class's process, the tests after it
fail as never run. The clock starts when the test does: starting the
process and collecting do not count, and each test of a class's process has
the whole limit of its own. The limit is a setting in pytest's
configuration, 900 unless set (2700 on an Intel Mac), and 0 means no limit::

    [tool.pytest.ini_options]
    socpuppet_platform_timeout = 60

pytest finds the plugin by itself where socpuppet is installed. Where the
package is imported straight from a source tree, enable it from a
``conftest.py``::

    pytest_plugins = ["socpuppet.pytest_plugin"]
"""

import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import time
from typing import IO, Any, Literal

import pytest

# Name of the environment variable that tells a child process where to write
# its test reports. A process that has it set is a child.
_REPORT_FILE_ENV = "SOCPUPPET_PYTEST_REPORT_FILE"

# The key of the line a child writes there when a test starts, which is when
# the parent starts the test's clock. No report of pytest's has it.
_STARTED = "started"

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


def patience_factor() -> int:
    """How many times longer than usual to wait on this machine, on the wall.

    Three on an Intel Mac, whose boots on the interpreter take up to three
    times as long as anywhere else with a test worker on every core, and one
    elsewhere.
    """
    intel_mac = (platform.system(), platform.machine()) == ("Darwin", "x86_64")
    return 3 if intel_mac else 1


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add the setting for how long a `platform` test may run."""
    parser.addini(
        _TIMEOUT_SETTING,
        "How many seconds a test marked `platform` may run before it is "
        "stopped and fails. 0 means no limit.",
        default=str(_DEFAULT_TIMEOUT_SECONDS * patience_factor()),
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


# What the session tells each xdist worker about how the tests are handed
# out, which the worker cannot see for itself: xdist sets a worker's
# ``--dist`` option to ``no`` (xdist/remote.py, setup_config), so a worker
# that asked would be told the tests are not being handed out at all.
_DIST_KEY = "socpuppet_dist"

# xdist's ways of handing tests out that give a class's tests to whichever
# worker is free, so that a class sharing one process would be booted by
# every worker that got one. ``loadgroup``, ``loadscope`` and ``loadfile``
# keep it on one worker, and ``--dist each`` gives every worker the whole
# class.
_SPLITS_A_CLASS = ("load", "worksteal")


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node: Any) -> None:
    """Tell an xdist worker how the tests are handed out (xdist's hook).

    ``node`` is xdist's controller of the worker, untyped: xdist ships no
    types. Optional, so that the plugin loads where xdist is not installed.
    """
    node.workerinput[_DIST_KEY] = node.config.getoption("dist")


def _dist_that_splits_a_class(config: pytest.Config) -> str | None:
    """The ``--dist`` way xdist is handing the tests out, if it splits a class.

    None in a session without xdist, and under a way that keeps a class on
    one worker.
    """
    workerinput: dict[str, Any] | None = getattr(config, "workerinput", None)
    dist = (workerinput or {}).get(_DIST_KEY)
    return dist if dist in _SPLITS_A_CLASS else None


# A test's node id as it was collected, before xdist's --dist loadgroup
# renamed it after its group: the name the test's own process knows it by.
_collected_as = pytest.StashKey[str]()


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Group the tests that share a class's process, for xdist's loadgroup.

    Before xdist's own hook, which reads the groups. Under ``--dist
    loadgroup`` a group goes to one worker and every other test is handed
    out alone, so that a class whose tests each boot spreads its boots out.
    """
    for item in items:
        item.stash[_collected_as] = item.nodeid
        if _shares_its_classs_process(item):
            item.add_marker(pytest.mark.xdist_group(_process_shared_by(item)))


def _collected_id(item: pytest.Item) -> str:
    return item.stash[_collected_as]


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
        # As the session knows the test, which xdist may have renamed.
        report.nodeid = item.nodeid
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
    if _collected_id(item) in waiting:
        return waiting.pop(_collected_id(item))
    if not _shares_its_classs_process(item):
        return _run_in_child_process([item])[_collected_id(item)]
    splits = _dist_that_splits_a_class(item.config)
    if splits is not None:
        return [
            _unfinished_report(
                item,
                f"Not run: --dist {splits} hands the tests of a class that "
                "shares one process out to several workers, and each would "
                "boot it again. Run with --dist loadgroup, which keeps them "
                "on one worker.",
                phases_reported=set(),
            )
        ]
    together = [
        each
        for each in item.session.items
        if _shares_its_classs_process(each)
        and _runs_in_a_process(each)
        and _process_shared_by(each) == _process_shared_by(item)
    ]
    reports = _run_in_child_process(together)
    waiting.update(reports)
    return waiting.pop(_collected_id(item))


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


def _process_shared_by(item: pytest.Item) -> str:
    """The process a test of a sharing class shares: its class's, by name.

    A class-scoped fixture with parameters is made once for each, and each
    would be a platform of its own, so each has a process of its own. All
    of a test's parameters count, its method's own too.

    ⚠️ No ``]`` anywhere in the name: xdist takes one after the ``@`` it
    adds for a parameter's id, and the test for one with no group.
    """
    its_class = item.getparent(pytest.Class)
    assert its_class is not None, "only a class's tests share a process"
    callspec = getattr(item, "callspec", None)
    return f"{its_class.nodeid} {callspec.id}" if callspec else its_class.nodeid


class _ChildReporter:
    """In the child: writes each test report where the parent will read it."""

    def __init__(self, config: pytest.Config, report_file: str) -> None:
        self._config = config
        self._report_file = report_file

    def pytest_runtest_logstart(self, nodeid: str) -> None:
        self._write({_STARTED: nodeid})

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self._write(
            self._config.hook.pytest_report_to_serializable(
                config=self._config, report=report
            )
        )

    def _write(self, data: dict[str, Any]) -> None:
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
    with tempfile.NamedTemporaryFile(mode="rb", suffix=".jsonl") as report_file:
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
                *(str(config.rootpath / _collected_id(item)) for item in items),
            ],
            env={**os.environ, _REPORT_FILE_ENV: report_file.name},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr, timed_out = _wait_for_child(child, report_file, timeout)
        if timed_out:
            unfinished = (
                f"The test ran for longer than {_seconds(timeout)} and was "
                "stopped. A script or a firmware that loops for ever is the "
                "usual cause. If the test needs longer, raise "
                f"{_TIMEOUT_SETTING} in pytest's configuration."
            )
        elif child.returncode not in _FINISHED:
            unfinished = (
                "The test's process exited with status "
                f"{describe_exit_status(child.returncode)} instead of "
                "finishing."
            )
        else:
            unfinished = None
        output = stdout + stderr
        reports: dict[str, list[pytest.TestReport]] = {
            _collected_id(item): [] for item in items
        }
        report_file.seek(0)
        for line in report_file:
            data = json.loads(line)
            if _STARTED in data:
                # Only the clock needed it.
                continue
            report = _report_from_json(config, data)
            # ⚠️ The options added to every run, PYTEST_ADDOPTS and addopts
            # in the configuration, reach the child too, so it can run and
            # report more than it was asked: a test file named there. The
            # session runs and reports those itself, so what the child says
            # of them is left out.
            if report.nodeid in reports:
                reports[report.nodeid].append(report)
    if unfinished is not None:
        # Each test that did not get as far as its teardown was cut short.
        # If every one did, the process died on its way out, after the last.
        cut_short = [
            item
            for item in items
            if "teardown" not in {r.when for r in reports[_collected_id(item)]}
        ] or items[-1:]
        # The first was the one running; the rest never started.
        first, *never_started = cut_short
        reports[_collected_id(first)].append(
            _unfinished_report(
                first,
                f"{unfinished} Its output follows.\n\n{output}",
                phases_reported={r.when for r in reports[_collected_id(first)]},
            )
        )
        for item in never_started:
            reports[_collected_id(item)].append(
                _unfinished_report(
                    item,
                    "Never ran: the class's process died during "
                    f"{first.nodeid}.",
                    phases_reported=set(),
                )
            )
    return reports


# How often the parent looks for a test that has started, while it waits.
_POLL_SECONDS = 0.1


def _wait_for_child(
    child: subprocess.Popen[str], report_file: IO[bytes], timeout: float
) -> tuple[str, str, bool]:
    """Wait for a child to end, and stop it if a test runs out of time.

    Each test has ``timeout`` seconds from the line in ``report_file`` that
    says it started, and 0 is no limit. Returns what the child wrote to
    stdout and stderr, and whether it was stopped.
    """
    # ⚠️ No limit until the first test starts. The session collected the
    # same files with the same conftests before it started the child, so a
    # collection that never ends has held the session up already.
    deadline = float("inf")
    while True:
        try:
            stdout, stderr = child.communicate(timeout=_POLL_SECONDS)
            return stdout, stderr, False
        except subprocess.TimeoutExpired:
            # Nothing the child wrote is lost: the next call carries on.
            pass
        if timeout and _a_test_started(report_file):
            deadline = time.monotonic() + timeout
        if time.monotonic() > deadline:
            stdout, stderr = _stop(child)
            return stdout, stderr, True


def _a_test_started(report_file: IO[bytes]) -> bool:
    """Whether the child has started a test since the last time it was asked.

    Reads the lines the child has finished writing, and leaves a line it is
    still in the middle of for the next time: the file is binary, so that
    ``tell`` and ``seek`` count bytes and a half-written line can be read
    again.
    """
    started = False
    while True:
        at = report_file.tell()
        line = report_file.readline()
        if not line.endswith(b"\n"):
            report_file.seek(at)
            return started
        started = started or _STARTED in json.loads(line)


def _report_from_json(
    config: pytest.Config, data: dict[str, Any]
) -> pytest.TestReport:
    """A report the child wrote, as pytest gave it there.

    ⚠️ A skip's reason is a tuple of where and why, which JSON brings back
    as a list, and pytest's summary of skips takes only a tuple.
    """
    if data.get("outcome") == "skipped" and isinstance(data["longrepr"], list):
        data["longrepr"] = tuple(data["longrepr"])
    report: pytest.TestReport = config.hook.pytest_report_from_serializable(
        config=config, data=data
    )
    return report


def _unfinished_report(
    item: pytest.Item, why: str, phases_reported: set[str]
) -> pytest.TestReport:
    """A failed report for a test its process did not finish, or never ran."""
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
