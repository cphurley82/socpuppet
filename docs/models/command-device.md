# Command device

Not a component you can place: the three registers that two of them begin with. C++ `socpuppet::CommandDevice` and `socpuppet::CommandStatus` · register map `regs/command_device.rdl`

## What it stands for

A device that its CPU gives one command at a time. The firmware says what it wants in the device's other registers, writes a command, and is told when the command has been carried out. The [DMA engine](dma-engine.md) and the [flash controller](flash-controller.md) both work this way, and real controllers are full of blocks that do.

💡 Both have these three registers at the same places, with the same bits, so a driver for one is most of a driver for the other. That is held, not hoped for: each device's register map has the three by the types this one defines, and `tools/regs.py` refuses a map that has one of them anywhere else.

## The registers

Each is 32 bits wide.

<!-- regs:command_device start -->

| Offset | Name | Access | What it is |
| --- | --- | --- | --- |
| `0x00` | `COMMAND` | write | Write a command to have it carried out. Reads as zero. |
| `0x04` | `STATUS` | read, write | How the last command went. Giving the next command forgets it. Bit 0 `DONE` (write one to clear): The command was carried out. Bit 1 `ERROR` (write one to clear): The command was not carried out, or not all of it. Bit 2 `BUSY` (read only): A command has been given and is not yet carried out. No other is taken meanwhile. |
| `0x08` | `INTERRUPT_ENABLE` | read, write | Which bits of `STATUS` raise the interrupt line while they are set. Bit 0 `DONE`. Bit 1 `ERROR`. |

<!-- regs:command_device end -->

A device's own registers come after these, from `0x0C`, and what its `COMMAND` can be told is its own: see the device's page.

### Giving it a command

```text
 firmware                          device
    │ write the device's own registers
    │ write COMMAND ──────────────▶ STATUS = BUSY
    │                               (a delta cycle later) does the work
    │                               STATUS = DONE, or ERROR
    │ ◀──────────────────────────── the interrupt line rises, if enabled
    │ read STATUS
    │ write a one to DONE or ERROR ▶ the line falls
```

- **A command is about what the registers said when it was given.** The firmware may describe the next command while this one is still busy.
- **One command at a time.** A write to `COMMAND` while the device is busy is refused.
- **The status is always about the last command.** Giving the next one forgets how the last one went.
- **`BUSY` cannot be cleared.** The CPU clears `DONE` or `ERROR` by writing a one to it, and the device interrupts for as long as a bit the CPU has enabled is set.

## Under the hood

- `regs/command_device.rdl` is the register map, in SystemRDL. `tools/regs.py` writes the table above from it, and the C header and the Python module that the rest go by.
- `src/socpuppet/core/command_status.h` is the status and interrupt-enable registers, with no simulator in it.
- `src/socpuppet/models/command_device.h` is the SystemC shell of any such device: the process that does the work, and the one process that drives the interrupt line.
- `python/socpuppet/zephyr_module/drivers/ssd/command_status.h` is the part the two Zephyr drivers share: give a command, and wait for it.
- `tests/cpp/unit/command_status_test.cpp` says what the two registers do, one behaviour each.
