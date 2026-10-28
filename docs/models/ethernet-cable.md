# 🔌 Ethernet cable (to this machine's network)

`sp.EthernetCable(card, forward={2222: 22}, capture="cable.pcap")` · Python only, no registry name · needs libslirp

## What it stands for

🔌 A cable from a network card of the platform's to a switch port on a small network, with a router on it, and the router is this machine. Linux on the host gets an address from the router's DHCP server, reaches this machine and whatever this machine reaches, and a port of this machine's can be forwarded to one of Linux's, so that `ssh` from a second terminal, a script or an IDE reaches the simulated Linux the way it reaches a server. It needs no root, no bridge and no TAP device.

🎓 The router is [libslirp](https://gitlab.freedesktop.org/slirp/libslirp), the library behind QEMU's user-mode network (`-netdev user`): a TCP/IP stack that answers the guest's frames as a router would, and opens sockets of this machine's own for whatever the guest connects to. To this machine it is a program like any other, which is why it needs no privilege.

```text
 ssh, scp ─▶ 127.0.0.1:2222 ─▶ libslirp ─▶ EthernetCable ─▶ card ─▶ Linux's eth0 :22
 Linux's eth0 ─▶ card ─▶ EthernetCable ─▶ libslirp ─▶ this machine's sockets ─▶ anywhere
```

The guest's network is QEMU's: 10.0.2.0/24, the gateway (this machine, as the guest sees it) at 10.0.2.2, a DNS relay at 10.0.2.3 that asks this machine's own resolver, and the guest's address, the first the DHCP server gives, 10.0.2.15.

## Getting it

libslirp is a system package, found where the system keeps libraries (or where Homebrew puts it on an Apple silicon Mac), and 🩺 the doctor's `cable` area looks for it, and for `ssh` and `scp`:

```sh
sudo apt-get install -y libslirp-dev openssh-client    # Ubuntu
brew install libslirp                                  # macOS, which has ssh
uv run python tools/doctor.py cable
```

Without it, `sp.EthernetCable` raises `sp.SlirpUnavailable`, which says how to install it, and `socpuppet linux` boots with the card unplugged and says so in one line.

## What it does

```python
import socpuppet as sp
from socpuppet.pump import pump

board.platform.build()
with sp.EthernetCable(board.virtio.net, forward={2222: 22}) as cable:
    pump(board.platform, far_ends=[cable], until=lambda: done)
```

Or, from a shell, `socpuppet linux`, which plugs one in with port 2222 forwarded to Linux's 22 ([linux.md](../linux.md#over-ssh)).

- 🧵 **A far end, pumped.** The cable is outside the simulation as much as in it, as a keyboard is, and `socpuppet.pump.pump` runs the platform and keeps up with it. At each look (`refresh()`) the frames the firmware sent since the last go to libslirp, and slirp handles its sockets and timers; what slirp sends goes to the card at once, which takes it into the firmware's next buffer. Its descriptor (`fileno()`) is readable when any of slirp's sockets is ready, one descriptor for all of them as `/dev/pciem`'s is for the drive's host, and `due_in()` says when slirp's timers are next due: never more than a second, half that while a TCP connection is open.
- **Any card.** The card is anything with `received_since(n)` and `send(frame)`, as 🎭 the [virtio network device](virtio-net.md) has; M17's real card takes the same cable.
- **Forwarded ports.** Each of `forward`'s ports of this machine's is listened on at 127.0.0.1 alone, and a connection to it becomes one to the firmware's port it maps to. A port that cannot be listened on, such as one that is taken, is an `OSError`, and the cable closes what it opened.
- **Plugged in at any time.** What the firmware sent before goes nowhere, as on a wire with nothing at its far end. The exit test boots Linux as fast as the simulation goes and plugs the cable in at the prompt; udhcpc, asking in the background, gets its address at its next try.
- **A capture.** With `capture`, every frame both ways is written to a pcap file, which Wireshark and `tcpdump -r` open. 🎓 Each frame is stamped with this machine's clock when the cable handles it, not with simulated time, so the gaps between frames are the pump's, not the firmware's.
- 💡 **slirp's clock is the wall's.** Its sockets are this machine's, and the pump waits on the wall while the CPU sleeps, so slirp's timers keep the wall's time. The guest's own timers keep the simulated clock, which runs ahead of the wall while the CPU works: TCP's retransmissions come early, by the guest's clock, and a 256 KiB `scp` goes through regardless.

## What it leaves out

What QEMU's user-mode network leaves out:

- **A way in, except by a forwarded port.** Nothing outside this machine can reach the guest, and nothing on this machine can either, but at a forwarded port.
- **Ping beyond the gateway**, except where this machine lets a program ping without root (`net.ipv4.ping_group_range`). The gateway answers ping itself.
- **IPv6.** slirp's IPv6 is off, and with it the only timer and the only guest-error report slirp has: Linux's IPv6 frames go nowhere.
- **Speed.** A frame costs a look of the pump, and TCP's keys are made on the simulated CPU: an `ssh` takes seconds on the interpreter, and less on QBox's hart.

## Where it comes from

💡 Borrowed. The network stack is [libslirp](https://gitlab.freedesktop.org/slirp/libslirp)'s, the system's own (4.9.1 where it was written, and its configuration of version 1, which every distribution's has). It has no Python binding, so the glue is ours: `python/socpuppet/slirp.py`, ctypes, the one place socpuppet knows libslirp's C ABI. `python/socpuppet/ethernet_cable.py` is the far end.

What socpuppet relies on of libslirp is its contract suite, `tests/python/test_slirp_contract.py`, where the test plays the guest's frames by hand, with no platform: a DHCP offer of 10.0.2.15, an ARP answer for the gateway, a forwarded port's connection with bytes both ways, a taken port refused. `tests/python/test_ethernet_cable.py` plugs the cable into the virtio card driven by 🧵 `sp.VirtioNetHost`, and `tests/python/test_ssh_over_the_cable.py` is the whole of it: this machine's `ssh` runs `uname -a` on Linux, on both harts, and its `scp` sends a file that the shell at the console reads back. What libslirp gets wrong is in [upstream.md](../upstream.md#libslirp).
