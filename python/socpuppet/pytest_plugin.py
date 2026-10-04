"""pytest support for tests that build a socpuppet Platform.

The SystemC kernel can be started only once per process, so a process can
hold only one Platform. Mark a test with ``@pytest.mark.platform`` and this
plugin runs it in a fresh Python process of its own.

A fresh interpreter is used rather than fork() (as pytest-forked does)
because forking is unsafe on macOS and a forked child inherits whatever
kernel state the parent already has. The cost is one pytest startup per
marked test.

Enable the plugin from a ``conftest.py``::

    pytest_plugins = ["socpuppet.pytest_plugin"]
"""

import json
import os
import signal
import subprocess
import sys
import tempfile

import pytest

# Name of the environment variable that tells a child process where to write
# its test reports. A process that has it set is a child.
_REPORT_FILE_ENV = "SOCPUPPET_PYTEST_REPORT_FILE"

# pytest's own exit statuses for "all passed" and "some tests failed". Any
# other status means the process did not get to finish normally.
_FINISHED = (pytest.ExitCode.OK, pytest.ExitCode.TESTS_FAILED)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "platform: builds a Platform, so the test runs in its own process "
        "(one SystemC kernel per process)",
    )
    report_file = os.environ.get(_REPORT_FILE_ENV)
    if report_file:
        config.pluginmanager.register(_ChildReporter(config, report_file))


def pytest_runtest_protocol(item, nextitem):
    if item.get_closest_marker("platform") is None or _REPORT_FILE_ENV in os.environ:
        return None  # run normally, in this process

    item.ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
    for report in _run_in_child_process(item):
        item.ihook.pytest_runtest_logreport(report=report)
    # The test's own fixtures lived and died in the child. Here, pytest still
    # has to finish with any class or module it set up for earlier tests and
    # that the next test does not share. There is no public hook for just
    # that, so this reaches into pytest's setup state; a test in
    # test_pytest_plugin.py pins the behavior.
    item.session._setupstate.teardown_exact(nextitem)
    item.ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)
    return True


class _ChildReporter:
    """In the child: writes each test report where the parent will read it."""

    def __init__(self, config, report_file):
        self._config = config
        self._report_file = report_file

    def pytest_runtest_logreport(self, report):
        data = self._config.hook.pytest_report_to_serializable(config=self._config, report=report)
        with open(self._report_file, "a") as out:
            out.write(json.dumps(data) + "\n")


def _run_in_child_process(item):
    """Run one test in a fresh interpreter and return its reports."""
    config = item.config
    with tempfile.NamedTemporaryFile(mode="r", suffix=".jsonl") as report_file:
        child = subprocess.run(
            # A node id is relative to the rootdir, so anchor it there. The
            # child keeps our working directory, as an unmarked test would.
            [sys.executable, "-m", "pytest", "--rootdir", str(config.rootpath),
             str(config.rootpath / item.nodeid)],
            env={**os.environ, _REPORT_FILE_ENV: report_file.name},
            capture_output=True,
            text=True,
        )
        reports = [
            config.hook.pytest_report_from_serializable(config=config, data=json.loads(line))
            for line in report_file
        ]
    if child.returncode not in _FINISHED:
        reports.append(_crash_report(item, child, phases_reported={r.when for r in reports}))
    return reports


def _crash_report(item, child, phases_reported):
    """A failed report for a child process that died instead of finishing."""
    # Blame the first phase that never reported, so the test is counted once.
    # If every phase reported, the crash came afterwards, on the way out.
    when = next(
        (phase for phase in ("setup", "call") if phase not in phases_reported), "teardown"
    )
    return pytest.TestReport(
        nodeid=item.nodeid,
        location=item.location,
        keywords=dict(item.keywords),
        outcome="failed",
        longrepr=(
            f"The test's process exited with status {_describe(child.returncode)} "
            f"instead of finishing. Its output follows.\n\n{child.stdout}{child.stderr}"
        ),
        when=when,
    )


def _describe(returncode):
    if returncode < 0:
        return f"{returncode} ({signal.Signals(-returncode).name})"
    return str(returncode)
