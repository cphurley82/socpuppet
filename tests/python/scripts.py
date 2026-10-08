"""Small scripts for scripted bus masters, shared by the tests."""

import socpuppet as sp


def writing(writes):
    """A script that writes each (address, value) pair in order."""

    def script():
        for address, value in writes:
            yield sp.write32(address, value)

    return script


def play(steps, bus):
    """Plays a driver's steps against `bus`, with no simulator.

    `bus` is a function that is handed each operation and returns what the
    operation gives back. Returns what the steps return.
    """
    try:
        operation = next(steps)
        while True:
            operation = steps.send(bus(operation))
    except StopIteration as done:
        return done.value
