# 🎭 PCIe host

`sp.PcieHost(ecam=...)` and `sp.MsiHost(receiver=...)` · Python only, `python/socpuppet/pcie_host.py` and `msi_host.py`

## What it stands in for

The part of a host's firmware that finds PCIe devices and sets them up, before any driver runs. On the finished platform that is Zephyr's PCIe code on the host CPU. 🚧 Until that boots, this stands in for it.

## What it does

Like the [NVMe host driver](nvme-host.md), it is not a component but steps for a script:

```python
def script():
    pci = sp.PcieHost(ecam=ECAM_BASE)
    msi = sp.MsiHost(receiver=MSI_BASE)

    (drive,) = yield from pci.scan()                  # 1. find it
    yield from pci.place(drive, WINDOW_BASE)          # 2. place its registers
    yield from pci.route_interrupts(drive, to=msi)    # 3. route its interrupts

    nvme = sp.NvmeHost(registers=WINDOW_BASE, memory=RAM_BASE,
                       interrupt=msi.wait)            # 4. now a driver can run
    yield from nvme.enable()
```

- **`scan()`** reads the first register of every slot on the bus and returns what it finds as `sp.PcieFunction`s: where each is, and its vendor, device and class. 🎓 This is *enumeration*. Nothing tells a host what devices it has.
- **`place(function, address)`** writes the address into the function's base address register and switches the function on: memory decoding, so that its registers answer, and bus mastering, so that it may do DMA and interrupt. An address the function cannot be at (not a multiple of its size) raises `sp.PcieError`.
- **`route_interrupts(function, to=msi)`** finds the function's MSI-X table and fills it in, so that every vector's message goes where `msi` says, and then switches MSI-X on.
- **`sp.MsiHost`** is the host's side of an [MSI receiver](msi-receiver.md): what a device is to be told to send, and `wait()`, which waits for the host's interrupt line and reads the receiver, which is what makes the line fall again.

The whole show, from a bus with something on it to a block read back, is `examples/nvme_hello.py`.

## What it leaves out

- **Most of enumeration.** One bus, function 0 of each device, no bridges to look behind. It does not size anything or share out the window: the script says where each function goes.
- **Any BAR but the first, and any interrupt but MSI-X.**
- **Per-vector handling.** `wait()` says which vectors fired and the NVMe driver here does not look, because it only ever waits for one thing.

## Under the hood

Each step is a generator of bus operations, so it can be played with no simulator at all. `tests/python/test_pcie.py` tests the rarer paths that way, against a dictionary standing in for a function's configuration space.
