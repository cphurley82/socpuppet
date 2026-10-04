"""The exceptions socpuppet raises."""


class ExpectationFailed(AssertionError):
    """A script expected one value in memory and read another."""
