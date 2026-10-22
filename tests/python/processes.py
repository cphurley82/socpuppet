"""Fresh Python processes for the tests that need one.

A test needs one when what it checks belongs to a whole process: what gets
imported, how a signal is taken, what a command prints.
"""

import contextlib
import os
import subprocess
import sys
import textwrap


def environment(**extra):
    """The environment a fresh interpreter needs to import what we can.

    `extra` is added to it, and what this process has in its own
    environment is passed on.
    """
    return {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path), **extra}


def run_python(code):
    """Run a snippet in a fresh interpreter and return what it printed."""
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        env=environment(),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


# What tells a new interpreter that coverage.py is to measure it. The build's
# `coverage` target runs the tests with these set (see .coveragerc).
COVERAGE_SWITCHES = ("COVERAGE_PROCESS_START", "COVERAGE_PROCESS_CONFIG")


def unmeasured(environment):
    """The same environment, for a process coverage.py is to leave alone."""
    return {
        name: value
        for name, value in environment.items()
        if name not in COVERAGE_SWITCHES
    }


def start_python(code, *, measured=True):
    """Start a snippet in a fresh interpreter, with its output piped back.

    A process that is not `measured` is one coverage.py leaves alone, even
    when it is measuring the tests.
    """
    return subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(code)],
        env=environment() if measured else unmeasured(environment()),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def run_socpuppet(
    *arguments, check=True, input=None, timeout=None, **extra_environment
):
    """Run the socpuppet command line, and return the finished process.

    `input` is piped to it, if any, and it is stopped after `timeout`
    seconds, if given. Unless `check` is false, a command that fails fails
    the test, with what it wrote to its standard error.
    """
    result = subprocess.run(
        [sys.executable, "-m", "socpuppet", *arguments],
        env=environment(**extra_environment),
        capture_output=True,
        text=True,
        input=input,
        timeout=timeout,
    )
    if check:
        assert result.returncode == 0, result.stderr
    return result


def start_socpuppet(*arguments, **extra_environment):
    """Start the socpuppet command line, with its output piped back."""
    return subprocess.Popen(
        [sys.executable, "-m", "socpuppet", *arguments],
        env=environment(**extra_environment),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


@contextlib.contextmanager
def ended_or_killed(process):
    """Give `process`; kill it when the `with` ends, if it still runs.

    A run that did not end is a test that failed, not one that hangs.
    """
    try:
        yield process
    finally:
        process.kill()
        process.wait()


def run_file(path, **extra_environment):
    """Run a Python file as a program, and return the finished process."""
    return subprocess.run(
        [sys.executable, str(path)],
        env=environment(**extra_environment),
        capture_output=True,
        text=True,
    )
