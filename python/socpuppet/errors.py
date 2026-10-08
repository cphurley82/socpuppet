"""The exceptions socpuppet raises."""


class ExpectationFailed(AssertionError):
    """A script expected one value in memory and read another."""


class BusError(RuntimeError):
    """A script's read or write was refused by the bus.

    Nothing is mapped at the address, or the target would not take an
    access of that size.
    """


class NvmeError(RuntimeError):
    """An NVMe controller did not do what the host's driver asked."""


class PcieError(RuntimeError):
    """A PCIe device does not have what the host's PCI code needs of it."""
