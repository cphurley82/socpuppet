"""Fresh Python processes for the tests that need one.

A test needs one when what it checks belongs to a whole process: what gets
imported, how a signal is taken, what a command prints.
"""

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


def start_python(code):
    """Start a snippet in a fresh interpreter, with its output piped back."""
    return subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(code)],
        env=environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def run_socpuppet(*arguments, check=True):
    """Run the socpuppet command line, and return the finished process.

    Unless `check` is false, a command that fails fails the test, with
    what it wrote to its standard error.
    """
    result = subprocess.run(
        [sys.executable, "-m", "socpuppet", *arguments],
        env=environment(),
        capture_output=True,
        text=True,
    )
    if check:
        assert result.returncode == 0, result.stderr
    return result


def run_file(path, **extra_environment):
    """Run a Python file as a program, and return the finished process."""
    return subprocess.run(
        [sys.executable, str(path)],
        env=environment(**extra_environment),
        capture_output=True,
        text=True,
    )
