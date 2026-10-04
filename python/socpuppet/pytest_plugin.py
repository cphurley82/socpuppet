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

import os
import subprocess
import sys

import pytest

# Set in the child process, so the child runs the test instead of spawning
# yet another process for it.
_CHILD_FLAG = "SOCPUPPET_PYTEST_CHILD"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "platform: builds a Platform, so the test runs in its own process "
        "(one SystemC kernel per process)",
    )


def pytest_runtest_protocol(item, nextitem):
    if item.get_closest_marker("platform") is None or os.environ.get(_CHILD_FLAG):
        return None  # run normally, in this process

    item.ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
    child = subprocess.run(
        [sys.executable, "-m", "pytest", "--rootdir", str(item.config.rootpath), item.nodeid],
        cwd=item.config.invocation_params.dir,
        env={**os.environ, _CHILD_FLAG: "1"},
        capture_output=True,
        text=True,
    )
    report = pytest.TestReport(
        nodeid=item.nodeid,
        location=item.location,
        keywords=dict(item.keywords),
        outcome="passed" if child.returncode == 0 else "failed",
        longrepr=None if child.returncode == 0 else child.stdout + child.stderr,
        when="call",
    )
    item.ihook.pytest_runtest_logreport(report=report)
    item.ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)
    return True
