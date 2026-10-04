"""Small scripts for scripted bus masters, shared by the tests."""

import socpuppet as sp


def writing(writes):
    """A script that writes each (address, value) pair in order."""

    def script():
        for address, value in writes:
            yield sp.write32(address, value)

    return script
