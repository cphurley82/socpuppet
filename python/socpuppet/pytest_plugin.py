"""pytest support for tests that build a socpuppet Platform.

The SystemC kernel can be started only once per process, so a process can
hold only one Platform. Mark a test with ``@pytest.mark.platform`` and this
plugin runs it in a fresh Python process of its own.

A fresh interpreter is used rather than fork() (as pytest-forked does)
because forking is unsafe on macOS and a forked child inherits whatever
kernel state the parent already has. The cost is one pytest startup per
marked test.

A marked test that runs for longer than ``socpuppet_platform_timeout``
seconds is stopped and fails. The limit is a setting in pytest's
configuration, 900 unless set, and 0 means no limit::

    [tool.pytest.ini_options]
    socpuppet_platform_timeout = 60

A test that is worth running but too long to run every time, such as a
boot the slow way round, is marked ``@pytest.mark.on_demand("why")``,
and is skipped unless the environment variable ``SOCPUPPET_ON_DEMAND``
is ``1``. It is a variable and not an option of pytest's, so that it
reaches the process a ``platform`` test runs in.

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


# The variable that runs the tests marked `on_demand`, and what it says.
_ON_DEMAND_ENV = "SOCPUPPET_ON_DEMAND"
_ON_DEMAND_ASKED = "1"


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
        "platform: builds a Platform, so the test runs in its own process "
        "(one SystemC kernel per process)",
    )
    config.addinivalue_line(
        "markers",
        f"on_demand(reason): skipped unless {_ON_DEMAND_ENV}="
        f"{_ON_DEMAND_ASKED}, for a test too long to run every time",
    )
    report_file = os.environ.get(_REPORT_FILE_ENV)
    if report_file:
        config.pluginmanager.register(_ChildReporter(config, report_file))


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip the `on_demand` tests, unless the environment asks for them."""
    if os.environ.get(_ON_DEMAND_ENV) == _ON_DEMAND_ASKED:
        return
    for item in items:
        marker = item.get_closest_marker("on_demand")
        if marker is not None:
            reason = marker.args[0] if marker.args else "on demand"
            item.add_marker(
                pytest.mark.skip(
                    reason=f"{reason}: run with "
                    f"{_ON_DEMAND_ENV}={_ON_DEMAND_ASKED}"
                )
            )


def pytest_runtest_protocol(
    item: pytest.Item, nextitem: pytest.Item | None
) -> bool | None:
    """Run a `platform` test in a process of its own."""
    if (
        item.get_closest_marker("platform") is None
        or item.get_closest_marker("skip") is not None
        or _REPORT_FILE_ENV in os.environ
    ):
        # Run normally, in this process: a test that is skipped whatever
        # happens, an `on_demand` one among them, needs no process to skip.
        return None

    item.ihook.pytest_runtest_logstart(
        nodeid=item.nodeid, location=item.location
    )
    for report in _run_in_child_process(item):
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


def _run_in_child_process(item: pytest.Item) -> list[pytest.TestReport]:
    """Run one test in a fresh interpreter and return its reports."""
    config = item.config
    timeout = float(config.getini(_TIMEOUT_SETTING))
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
                str(config.rootpath / item.nodeid),
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
        reports = [_report_from_json(config, line) for line in report_file]
    if unfinished is not None:
        reports.append(
            _unfinished_report(
                item,
                f"{unfinished} Its output follows.\n\n{output}",
                phases_reported={r.when for r in reports},
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
