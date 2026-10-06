# 🎭 NVMe host driver

`sp.NvmeHost(registers=..., memory=...)` · Python only, `python/socpuppet/nvme_host.py`

## What it stands in for

The NVMe driver in the host's firmware: the code that finds the drive's registers, sets up queues in the host's memory, and turns "read block 7" into a command the drive understands. On the finished platform that is Zephyr's driver, running on the host CPU. 🚧 Until that boots, this stands in for it, and it stays on afterwards as the host for anyone bringing up SSD firmware.

🎓 It is also the shortest way to see what a driver does. The whole exchange is one function of five numbered steps, `_complete()`:

1. Write a 64-byte command into the next slot of a submission queue.
2. Ring the doorbell: write the queue's new tail to a register.
3. Wait for the interrupt, and read the 16-byte completion.
4. Ring the other doorbell, to say the completion has been read.
5. Look at the status the completion carries.

## What it does

It is not a component. It is a set of steps for a script, and a script hands over to it with `yield from`:

```python
def script():
    nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
    yield from nvme.enable()
    drive = yield from nvme.identify_namespace()        # .blocks, .block_size
    yield from nvme.write_blocks(first=0, data=bytes(512))
    block = yield from nvme.read_blocks(first=0, count=1)

platform = sp.Platform()
cpu = platform.add("cpu", sp.ScriptedBusMaster(script))
bus = platform.add("bus", sp.Router())
ram = platform.add("ram", sp.Memory(size=0x10_0000))
nvme = platform.add("nvme", sp.BehavioralNvme(blocks=2048))
platform.connect(cpu.socket, bus.target)
bus.map(ram.socket, base=RAM_BASE)
bus.map(nvme.bar0, base=NVME_BASE)
platform.connect(nvme.dma, bus.add_input())
platform.connect(nvme.irq0, cpu.irq)
```

- **`registers`** is where the controller's register block is in the host's address map.
- **`memory`** is the start of an area of the host's memory the driver may use: four pages for its queues, then as many pages as its largest transfer needs, and one more for a list of them. 💡 Nothing here is a special kind of memory. A driver's queues and buffers are ordinary RAM that it tells the controller about.
- **`enable()`** resets the controller, tells it where the admin queues are, enables it, and creates one pair of I/O queues. Calling it again starts over, and what is on the drive stays.
- **`identify_namespace()`** asks the drive how many blocks it has and how big they are.
- **`read_blocks()` and `write_blocks()`** move whole blocks, up to 513 pages of memory (a little over 2 MiB) in one command. The driver spreads the data over pages that need not be next to each other and tells the controller where each one is.
- **`interrupt=`** is how the driver waits for the controller's interrupt. Left out, it waits with `sp.wait_irq()`, which is right when the controller's first interrupt line is wired to the master that runs the script, as above. Behind PCIe the interrupt arrives as a message, and the thing to pass is `sp.MsiHost(...).wait` (see the [PCIe host](pcie-host.md)).
- **Errors.** A command the controller fails raises `sp.NvmeError` with the status's name, and so does a controller that does not become ready in the time it says it needs. Like any exception in a script, it comes out of `platform.run()`.

## What it leaves out

- **Finding the drive.** It is told where the registers are. Behind PCIe, finding them is the [PCIe host](pcie-host.md)'s job.
- **A vector per queue.** Every queue interrupts on vector 0, and the driver waits for one interrupt at a time.
- **Doing two things at once.** One command at a time: it sends one and waits for it. A real driver keeps many in flight and matches completions to commands by their identifiers.
- **Patience with a silent controller.** A command that never completes is never given up on: the script is still waiting when the run ends.
- **Most of what a driver has to get right**: more than one I/O queue or namespace, queues longer than a page, a timeout per command, retries, shutdown.

## Under the hood

Each step is a Python generator that yields bus operations (`sp.read32`, `sp.write`, `sp.wait_irq`), which is why it needs `yield from`. That also means it can be played with no simulator at all, by handing it the result of each operation: `tests/python/test_nvme_host.py` tests its error paths that way.
