# 🎭 IO-die manager

`sp.IoManager(link=...)` · Python `socpuppet.io_manager.IoManager`

## What it stands in for

The management firmware of a chiplet host's IO die: the first thing that runs when the power comes on, and the thing that decides the rest of the chip may start.

🎭 It is a stand-in, a Python script for a [scripted bus master](scripted-bus-master.md) in the place of the IO die's CPU, in the same shape as 🎭 [the SSD's firmware stand-in](ssd-firmware.md). The real thing is `firmware/iomgr`, a Zephyr application on the IO die's own RV32 core, which does the same four things.

## What it does

```python
manager = io.add("cpu", sp.ScriptedBusMaster(script=sp.IoManager(link=0x1001_0000).script))
platform.connect(d2d.b.irq, manager.irq)
```

Four steps, which is what firmware does and in the same order:

1. Ask [the link](d2d-link.md) to interrupt when its status changes, and write *start link training*.
2. Sleep until the link says it is up. Every wake is an interrupt, and each one acknowledges what the status says has happened, by writing a one back to it.
3. Let the compute die go: a mailbox write of zero to the reset register at the *other* end of the link, which is the register that holds that die's CPU.
4. Sleep. If the link goes down, write *retrain link* and wait for it again.

💡 Step 3 is the whole reason a chiplet host has a manager die. The compute die's CPU cannot release itself, and nothing but the sideband can reach across a link that is not up yet.

`socpuppet.boards.io_manager` is the board built around it, and `examples/io_manager_hello.py` is the show: a traced run that prints UCIe's whole bring-up, packet by packet, and then the compute die's first access across the link. The stand-in is also the manager of the host across the real link: `host(manager=functools.partial(add_manager, script=stand_in_manager().script))`, with both names from `socpuppet.boards.manager`, and `examples/chiplet_host_hello.py` is that show, with Zephyr on the compute die.

## What it leaves out

Everything else a manager would do: no console, no start-up of the rest of the IO die, no power or clock control, no telling anyone what went wrong. It keeps no state at all between steps.

⚠️ It raises if the other die never answers the mailbox, which in a described platform means the link's sideband is not joined to another endpoint.
