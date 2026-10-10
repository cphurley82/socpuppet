# Die-to-die link

`sp.D2dLink()` · C++ `socpuppet::D2dLinkEndpoint` · registry name `d2d_link_endpoint`

## What it stands for

The link between two dies in one package, in the style of [UCIe](https://www.uciexpress.org).

🎓 A chiplet design is one chip built from several dies. The dies have to be joined, and UCIe (Universal Chiplet Interconnect Express) is the open standard for joining them. A UCIe link has two paths. The **mainband** is the wide one that carries the dies' traffic, and it does not work until it has been trained. The **sideband** is a narrow management channel that is up from the start: it is how the two dies agree to bring the mainband up, and how the firmware on one die reaches the other's registers before anything else works.

```text
 compute die                                            IO die
 bus ─▶ target ══════ the mainband ══════▶ initiator ─▶ bus
        initiator ◀═══════════════════════ target  ◀─── bus
        sideband ─ its registers ══ the sideband ══ its registers ─ sideband
        reset ─▶ the die's CPU                            irq ─▶ the die's PLIC
```

⚠️ **UCIe-style, from public sources, and not compliant.** The training states, the register layout and the sideband message format follow UCIe as far as public material says what they are: the Hot Chips 2023 UCIe tutorial, and Berkeley's open [uciedigital](https://github.com/ucb-bar/uciedigital) RTL for the encodings. Nothing here comes from the specification, and whole layers of a real link are missing (below). What it is for is to make a chiplet boot flow real enough to learn from and to test firmware against.

## What it does

```python
d2d = platform.link("d2d", sp.D2dLink(), compute, io)   # one end per die
platform.connect(cpu.socket, compute_bus.target)
compute_bus.map(d2d.a.target, base=0, size=0x8000_0000)  # the window across
platform.connect(d2d.b.initiator, io_bus.add_input())    # what arrives
io_bus.map(d2d.b.sideband, base=0x1001_0000)             # the registers
platform.connect(d2d.b.irq, manager.irq)
platform.connect(d2d.a.reset, compute_cpu.reset)
```

| Port | What it is |
|---|---|
| `target` | Traffic leaving this die for the other. Refused until the link is up. |
| `initiator` | Traffic arriving on this die, with its crossing time already counted. |
| `peer_initiator`, `peer_target` | The mainband between the two ends. `platform.link()` binds them. |
| `sideband` | The link's own registers, 256 bytes, as this die's firmware reaches them. |
| `sideband_peer_initiator`, `sideband_peer_target` | The sideband between the two ends, also bound by `platform.link()`. |
| `reset` | High while this die is held in reset. The other die lowers it. |
| `irq` | High while the link has something to tell this die's firmware. |

| Parameter | What it is |
|---|---|
| `latency_ns` | How long the link takes to carry anything across. Default 20. |
| `bytes_per_ns` | How many bytes of it go in a nanosecond. Default 16. |
| `training_ns` | How long SBINIT to ACTIVE takes. Default 1 000 000, a millisecond. |

### Training

UCIe's link training state machine, as far as this model has it:

```text
 RESET ──▶ SBINIT ──▶ MBINIT ──▶ MBTRAIN ──▶ LINKINIT ──▶ ACTIVE
   ▲          │          │          │           │           │
   │          └──────────┴──────────┴───────────┴───────────┘
   │                          │ nobody answered, or a fault
   └────── retrained ── TRAINERROR ◀──────────┘
```

A link is held in RESET for at least 4 ms after power-on, which is UCIe's figure. The die whose firmware writes *start link training* then sends UCIe's requests, a state at a time, and the other die hears that it has left reset and walks the same states beside it, answering. Each of the four states takes a quarter of `training_ns`. A state nobody answers within 8 ms, UCIe's figure again, ends in TRAINERROR, and so does a fault; the far die is told, and nothing crosses the mainband until firmware asks for a retrain, which starts over from RESET.

The sideband handshake, as a traced run shows it. `ucie.sideband_packets(platform.trace)` reads the packets back, and `examples/io_manager_hello.py` prints them:

```text
 4000.000 us       io ─▶ {SBINIT Out of Reset}
 4000.000 us       io ─▶ {SBINIT Done Request}
 4000.000 us  compute ─▶ {SBINIT Done Response}
 4250.000 us       io ─▶ {MBINIT.PARAM configuration request}
 4250.000 us  compute ─▶ {MBINIT.PARAM configuration response}
 4250.000 us       io ─▶ {MBINIT.CAL Done Request}
 4250.000 us  compute ─▶ {MBINIT.CAL Done Response}
 4750.000 us       io ─▶ {LinkMgmt.RDI.Req.Active}
 4750.000 us  compute ─▶ {LinkMgmt.RDI.Rsp.Active}
 5000.000 us       io ─▶ MemoryWrite_32b 0x24 = 0x0      ← lets the other die go
 5000.000 us  compute ─▶ Completion, success
```

### The registers

UCIe's Link DVSEC: a designated vendor-specific extended capability of the kind PCIe defines, at a fixed place in memory rather than in a configuration space. Each register is 32 bits wide. `socpuppet.regs.ucie_link` has the same names for Python, and 🎭 [`sp.IoManager`](io-manager.md) is firmware that drives them.

<!-- regs:ucie_link start -->

| Offset | Name | Access | What it is |
| --- | --- | --- | --- |
| `0x00` | `EXTENDED_CAPABILITY_HEADER` | read | PCIe's extended capability header. At reset: `0x00010023`. Bits 15 to 0 `CAPABILITY_ID`: 0x0023, which says a designated vendor-specific capability. Bits 19 to 16 `VERSION`: The capability's version. Bits 31 to 20 `NEXT`: Where the next capability is. There is none. |
| `0x04` | `DVSEC_HEADER_1` | read | DVSEC header 1: whose capability it is. At reset: `0x1000D2DE`. Bits 15 to 0 `VENDOR_ID`: 0xD2DE, which is the vendor number UCIe registered. Bits 19 to 16 `REVISION`: The capability's revision. Bits 31 to 20 `LENGTH`: How long the capability is, in bytes: the whole block. |
| `0x08` | `DVSEC_HEADER_2` | read | DVSEC header 2: which of the vendor's capabilities it is. At reset: `0x00000001`. Bits 15 to 0 `DVSEC_ID`: ⚠️ Ours: public sources do not give UCIe's number for the link DVSEC. |
| `0x10` | `CONTROL` | write | UCIe's link control. Both bits are an action, clear themselves, and read as zero. Bit 0 `START_TRAINING`: Start link training. Bit 1 `RETRAIN`: Retrain the link, from reset. |
| `0x14` | `STATUS` | read, write | UCIe's link status. Bit 0 `UP` (read only): The link is up. Bit 1 `TRAINING` (read only): The link is being trained. Bit 2 `CHANGED` (write one to clear): The link has gone up or come down since this was cleared. Bit 3 `UNCORRECTABLE_FATAL` (write one to clear): The other die has reported an error nothing can be done about. |
| `0x18` | `EVENT_NOTIFICATION` | read, write | UCIe's link event notification: what raises `irq`. Bit 0 `STATUS_CHANGED`: Interrupt while the status says the link has changed. |
| `0x1C` | `REGISTER_LOCATOR` | read | The register locator: where the block of the link's own registers is. ⚠️ Its layout is ours. At reset: `0x00002001`. Bits 7 to 0 `BLOCK`: Which block it is. Bits 31 to 8 `OFFSET`: Where the block starts, from the start of the capability. |
| `0x20` | `TRAINING_STATE` | read | Which training state the link is in. ⚠️ The numbers are ours. 0 `RESET`: Held in reset, as every link is for 4 ms after power-on. 1 `SBINIT`: The sideband is being brought up. 2 `MBINIT`: The mainband's parameters are being agreed. 3 `MBTRAIN`: The mainband is being trained. 4 `LINKINIT`: The two ends are agreeing that the link is theirs to use. 5 `ACTIVE`: The link is up, and carries the dies' traffic. 6 `TRAIN_ERROR`: Training failed, or the link was broken. Only a retrain leaves this state. |
| `0x24` | `DIE_RESET` | read, write | The reset this end drives on its own die. At reset: `0x00000001`. Bit 0 `ASSERTED`: The die is held in reset. The other die lets it go by writing a zero here, through its mailbox. |
| `0x28` | `FAULT_INJECTION` | write | A way to break the link on purpose. Reads as zero. Bit 0 `BREAK`: Write a one to break the link. |
| `0x40` | `MAILBOX_OPCODE` | read, write | What the next access to the other end is to be. Bits 4 to 0 `CODE`: UCIe's opcode for it, which is five bits of a sideband packet. 0 `MEMORY_READ_32B`: Read a register of the other end. 1 `MEMORY_WRITE_32B`: Write one. |
| `0x48` | `MAILBOX_ADDRESS` | read, write | Which register of the other end: its offset in the block there. |
| `0x50` | `MAILBOX_DATA` | read, write | What to write. Reads as what the last read brought back. |
| `0x58` | `MAILBOX_TRIGGER` | write | Sends the access. Reads as zero. Bit 0 `GO`: Write a one to send it. |
| `0x5C` | `MAILBOX_STATUS` | read | How the last access went, and whether one is still on its way. Bits 2 to 0 `CODE`: How it went. 0 `SUCCESS`: The other end did it. 2 `UNSUPPORTED_REQUEST`: There is no such register at the other end, or it cannot be written. Bit 8 `BUSY`: An access has been sent and not yet answered. |

<!-- regs:ucie_link end -->

UCIe's capability has a link capability register at `0x0C` as well, which nothing here reads, so it is not modelled. It reads as zero, as every offset in the block does that has no register.

The **mailbox** is how firmware reaches the other end's registers: fill in an opcode (`MemoryRead_32b` or `MemoryWrite_32b`), an address in the other end's block and the data, write a one to the trigger, and watch the status until it is no longer busy. That is how a manager die lets a compute die go, by writing a zero to the other end's register at 0x24.

### Timing

A crossing costs `latency_ns` plus the transaction's bytes at `bytes_per_ns`, and each direction is serialized on its own: a transaction handed to a busy link waits for the bytes ahead of it. 64 bytes on the default link arrive 24 ns after they leave.

⚠️ A Python test cannot see 20 ns in `platform.time` after one write. A bus master may run up to a quantum (100 µs by default) ahead of the simulation's clock, and folds the delay into that. Measure through [the trace](tracer.md), whose records carry the arrival time, or set `platform.quantum = 0`.

### The Zephyr driver

`socpuppet,ucie-link` in socpuppet's Zephyr module (`drivers/d2d/ucie_link.c`). It is a driver of Zephyr's **reset** class: the die at the other end is its one line, `UCIE_LINK_THE_OTHER_DIE`, and `reset_line_deassert()` is the mailbox write that lets it go. Training is functions of its own, in `<socpuppet/drivers/ucie_link.h>`: `ucie_link_train()`, `ucie_link_retrain()`, `ucie_link_is_up()` and `ucie_link_wait_until_down()`. [boot-your-firmware.md](../boot-your-firmware.md#the-io-dies-manager) has the board and the firmware that uses it.

## What it leaves out

- **The physical layer.** No lanes, no clock, no speed negotiation, no repair of a broken lane. MBTRAIN is a state that takes time and does nothing.
- **The protocol layers.** Mainband traffic is a TLM transaction passed on as it is. There is no flit, no CRC, no retry, no credit, and no PCIe or CXL layer on top: the mainband is raw memory-mapped access.
- **PHYRETRAIN.** A retrain here starts over from RESET, so the state UCIe has for retraining in place has nothing to do.
- **Dropped and corrupted traffic.** A fault takes the whole link down; nothing can be injected finer than that. 🚧 M10 is where error injection gets interesting.
- **Power states.** No L1, no L2.
- **Negotiation.** The MBINIT.PARAM messages carry nothing: both ends are the same link, built from the same parameters.
- **Direct memory access.** Refused outright, so every access crosses the link and is seen taking its time.

## The contract

`LinkContract` (`tests/cpp/contracts/link_contract.h`), which 🎭 [the pass-through link](pass-through-link.md) passes too. The contract's rig trains this link first, through the registers above, and the pass-through's rig has nothing to train.
