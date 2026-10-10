# 🎭 Pass-through link

`sp.PassThroughLink()` · C++ `socpuppet::PassThroughLinkEndpoint` · registry name `pass_through_link_endpoint`

## What it stands in for

The die-to-die (D2D) link of a chiplet design: the connection between two dies in one package, in the style of [UCIe](https://www.uciexpress.org). On real hardware it is a physical layer that has to be trained before use, a protocol on top, and a sideband channel for management.

## What it does

```python
d2d = platform.link("d2d", sp.PassThroughLink(), compute, io)
platform.connect(cpu.socket, d2d.a.target)      # leaving the compute die
platform.connect(d2d.b.initiator, bus.target)   # arriving on the IO die
```

It hits the same marks as the real link in two respects, which is what lets everything around it be built first:

- **One endpoint per die.** `platform.link()` places an endpoint in each group and joins them. Each die's logic talks only to its own endpoint.
- **Traffic both ways.** `a.target` → `b.initiator`, and `b.target` → `a.initiator`. A device on the IO die is the target of a register access and, later, the initiator of a DMA write into the compute die's memory.

```text
this die                                    the other die
target ──────────▶ peer_initiator ════▶ peer_target ──────▶ initiator
initiator ◀─────── peer_target    ◀════ peer_initiator ◀─── target
```

Everything is passed on unchanged: transactions, debug accesses, and DMI.

## What it leaves out

Nearly everything that makes the real link interesting:

- **Link state.** No reset, training or retraining. The link is always up.
- **Latency and bandwidth.** Crossing it takes no time.
- **Errors.** Nothing is ever dropped or corrupted, and nothing can be injected.
- **Sideband.** There is no management channel and no control over the other die's reset.

⚠️ It also grants DMI, which the real link is planned not to: there, every access has to cross the link and be seen doing so. Software that relies on fast paths through this stand-in will slow down when the real link replaces it.

## The contract

Any link, this stand-in included, must pass `LinkContract` (`tests/cpp/contracts/link_contract.h`). The contract allows a link to refuse DMI, and [the real link](d2d-link.md) does.

The real link arrived in M5. Nothing it does needs a wire to cross: an interrupt or a reset is a message on its sideband, or it stays on its die. 💡 Swapping this stand-in for the real one is one line in a board, plus firmware to train the link — the stand-in's link is up from the start, and the real one is not.
