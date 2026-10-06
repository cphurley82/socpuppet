"""The exceptions socpuppet raises."""


class ExpectationFailed(AssertionError):
    """A script expected one value in memory and read another."""


class NvmeError(RuntimeError):
    """An NVMe controller did not do what the host's driver asked."""
