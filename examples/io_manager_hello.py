"""🧦 An IO die brings up the die-to-die link and lets the compute die go.

    compute die (🎭 a stand-in)                 IO die
    🎭 master ─▶ bus ─┬─▶ d2d.a ════ d2d.b ─▶ bus ─┬─▶ scratch
                      └─▶ ram          │           └─▶ the link's registers
               reset ◀─────────────────┤                     ▲
                                  irq ─┴─▶ 🎭 the manager ───┘

This is a chiplet host starting up. The link between the two dies is not
there when the power comes on: the IO die's manager has to train it, and
until then nothing crosses it and the compute die is held in reset.

🎭 Both dies are scripts here: `sp.IoManager` in the manager's place, and
a stand-in on the compute die that does one thing once it is let go, which
is to reach across the link into the IO die's memory.

The link is traced, so the show below is UCIe's own bring-up, packet by
packet, as `socpuppet.ucie` reads them back.

Run it:    python examples/io_manager_hello.py
"""

import socpuppet as sp
from socpuppet import ucie
from socpuppet.boards.io_manager import (
    HELLO,
    SCRATCH_BASE,
    io_manager,
    one_round_trip,
)

board = io_manager(compute=one_round_trip, trace=True)
board.platform.build()

print("🧦 the power is on. The link is in reset and the compute die with it.")
reached = board.platform.run_until(
    lambda: (
        board.platform.peek32(SCRATCH_BASE, via=board.manager.socket) == HELLO
    ),
    timeout=sp.ms(20),
)

print("\n📻 what the two ends said to each other on the sideband:")
for record in board.platform.trace:
    if not record.source.endswith("sideband_peer_initiator"):
        continue
    packet = ucie.SidebandPacket.from_bytes(record.data)
    if packet is None:
        continue
    die = "io" if record.source.startswith("io") else "compute"
    when = record.time / 1_000_000
    print(f"  {when:9.3f} us  {die:>7} ─▶ {packet.description()}")

print("\n🚌 and what then crossed the mainband:")
crossings = [
    record
    for record in board.platform.trace
    if record.source.endswith("d2d.peer_initiator")
]
for record in crossings:
    die = "io" if record.source.startswith("io") else "compute"
    print(
        f"  {record.time / 1_000_000:9.3f} us  {die:>7} ─▶ "
        f"{record.command} {record.address:#x} = {record.data.hex()}"
    )

if not reached:
    raise SystemExit("🧦 ❌ the compute die never reached the IO die")
print(
    f"\n🧦 ✅ the compute die read {HELLO:#x} back across the link, "
    f"{crossings[-1].time / 1_000_000:.3f} us after power-on. 💡 The 4 ms of "
    "that is UCIe's reset hold, and the millisecond after it is this "
    "link's training time."
)
