# 🎭 Virtio host driver

`sp.VirtioRngHost`, `sp.VirtioConsoleHost`, `sp.VirtioBlkHost`, `sp.VirtioNetHost`, `sp.VirtioFsHost`, on `sp.VirtioHost` · Python only, `python/socpuppet/virtio_host.py`

## What it stands in for

The driver of a virtio device, as a script: the code that finds the device, agrees on features, lays its virtqueues out in memory and hands it buffers. 🧵 It was each device's first driver here, before Zephyr's or EDK2's ran against it, and it is the shortest way to see what any of them does.

🎓 Every exchange is `submit(queue, readable, writable)`:

1. Write a descriptor for each buffer, chained, the device's to read first and its to write after.
2. Put the chain's head in the available ring, and move the ring's index on.
3. Ring the doorbell: write the queue's number to `QUEUE_NOTIFY`.
4. Wait for the interrupt, read `INTERRUPT_STATUS` and acknowledge it.
5. Read the used ring's element: which chain, and how many bytes the device wrote.

## What it does

It is not a component. It is steps for a script, handed over to with `yield from`:

```python
def script():
    disk = sp.VirtioBlkHost(registers=0x1000_3000, memory=RAM_BASE)
    yield from disk.start()        # probe, reset, negotiate, set the queues up, DRIVER_OK
    yield from disk.write_sectors(first=2, data=b"s" * 1024)
    data = yield from disk.read_sectors(first=2, count=2)
```

| Class | Device | What it adds |
|---|---|---|
| `VirtioRngHost` | entropy | `read(count)` |
| `VirtioConsoleHost` | console | `send(data)`, `receive(at_most)` |
| `VirtioBlkHost` | block | `read_sectors`, `write_sectors`; a failing status raises with what it likely means |
| `VirtioNetHost` | network | `send_frame`, `receive_frame` |
| `VirtioFsHost` | file system | `init`, `lookup`, `open`, `read`; a FUSE error raises with its Linux name |

`start()` checks the device's magic and kind and raises `sp.VirtioError` with what it found if either is wrong. `negotiate(wanted)` accepts only what the device offers, and `VERSION_1`, and raises if the device does not keep `FEATURES_OK`. `submit` is `post` and then `take`, for a script that wants a chain in flight while it does something else. The rings go in `memory`, a page each, from a bump allocator that never gives anything back: plenty for a test, and not a driver for a long run.

## What it leaves out

Any feature but `VERSION_1`, and memory given back: the rings and buffers come from a bump allocator.
