# 🎭 Virtio console

`sp.VirtioConsole()` · C++ `socpuppet::VirtioConsole` · registry name `virtio_console`

## What it stands for

🎭 A stand-in (a simplified model) for a serial port with no baud rate: the console QEMU gives a guest as `virtio-serial-device` with one port. 🎓 Device 3 in the specification (section 5.3): a receive queue the driver keeps stocked with empty buffers, and a transmit queue it puts bytes out on.

## What it does

```python
console = platform.add("console", sp.VirtioConsole())
bus.map(console.cpu, base=0x1000_2000)
platform.connect(console.dma, bus.add_input())
platform.connect(console.irq, aplic.source19)

platform.build()
platform.run(sp.ms(1))
print(console.output)       # what the firmware has put out
console.write("spam\n")     # typed at the other end
```

🧵 Whoever holds the console is the far end of its line, as at the [UART](ns16550.md): `output` and `write` are the same two calls, from one `FarEnd` the two share.

- **Transmits.** Each chain on the transmit queue is read whole, added to `output`, and given back at once with nothing written.
- **Receives.** An empty buffer on the receive queue is kept until something is typed. Typed bytes wait in the device until a buffer is there; each buffer takes as many as it holds. They go in a delta cycle after `write`, in a process of the device's own, since whoever types may be a script between two runs.
- **Interrupts for a held buffer given back,** with no doorbell: the transport asks the device to deliver at every turn, and raises its line when any queue's used ring has moved.

## What it leaves out

Every feature: no size (`F_SIZE`), no multiple ports (`F_MULTIPORT`, so no control queues), no emergency write (`F_EMERG_WRITE`). The configuration is empty.

## In a devicetree

`compatible = "virtio,mmio"` for its slot. In Zephyr's dialect a child, `virtio-console { compatible = "virtio,console"; }`, which Zephyr's console driver binds to. It is not `chosen` as Zephyr's console: the shield `socpuppet_host_virtio_console` says that, so that firmware is built to speak through it only when asked, and the 16550 stays the console otherwise.

## Who has driven it

🧵 `sp.VirtioConsoleHost`; Zephyr's `drivers/serial/uart_virtio_console.c`, through `samples/hello_world` with both shields. ⚠️ Zephyr's driver asks for queues of one entry, so each character after the first waits for the used-buffer interrupt to give its descriptor back. EDK2's image has no virtio console driver. Linux's `virtio_console` (`VIRTIO_CONSOLE`, built in) has not run against it.
