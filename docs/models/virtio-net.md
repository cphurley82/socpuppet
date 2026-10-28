# 🎭 Virtio network device

`sp.VirtioNet(mac=0x0200_5E00_5301)` · C++ `socpuppet::VirtioNet` · registry name `virtio_net`

## What it stands for

🎭 A stand-in (a simplified model) for an Ethernet port, with Python on the other end of the wire: QEMU's `virtio-net-device`. 🎓 Device 1 in the specification (section 5.1): a receive queue the driver keeps stocked with empty buffers, a transmit queue it sends frames on, and a 12-byte header in front of every frame both ways, for offloads this device offers none of.

## What it does

```python
net = platform.add("net", sp.VirtioNet(mac=0x0200_5E00_5301))   # 02:00:5e:00:53:01
bus.map(net.cpu, base=0x1000_4000)
platform.connect(net.dma, bus.add_input())
platform.connect(net.irq, aplic.source21)

platform.build()
platform.run(sp.ms(100))
for frame in net.received:   # every Ethernet frame the firmware sent
    ...
net.received_since(3)        # only those after its first three
net.send(frame)              # an Ethernet frame to the firmware
print(net.dropped)           # frames that were longer than the buffer for them
```

- **Sends.** A chain on the transmit queue, less its header, is a frame on the wire, in `received`. A far end that keeps up with the wire asks `received_since` for the frames after those it has taken, and only those are copied. It may be one buffer, as Zephyr sends, or a header and a frame, as EDK2 does.
- **Receives.** A frame Python sends waits until a buffer is held out, and goes in a delta cycle later, after a header whose `num_buffers` is 1. A buffer in two descriptors, as EDK2 gives them, takes the header in the first and the frame in the second.
- **Drops a frame longer than the buffer for it,** and counts it in `dropped`, as a card drops what it has no room for. The buffer waits for the next frame.
- **Offers `F_MAC`** and has its address in its configuration: EDK2's driver will not bind without it, and Linux's takes its address from there.

`tests/python/ethernet.py` makes and reads the frames a test needs with [dpkt](https://github.com/kbandla/dpkt): ARP requests, UDP datagrams, and a `Neighbour` that answers ARP and ping for an address of its own.

## What it leaves out

Checksum and segmentation offloads, merged receive buffers (`F_MRG_RXBUF`), a control queue (`F_CTRL_VQ`), more than one pair of queues, and a link status (`F_STATUS`): a driver that is not offered one takes the link to be up, and EDK2's `ifconfig` says `Media state unknown`.

## In a devicetree

`compatible = "virtio,mmio"` for its slot. In Zephyr's dialect a child, `virtio-net { compatible = "virtio,net"; local-mac-address = [...]; }`: Zephyr's driver takes its address from the devicetree and never from the device. Linux's node is the transport's alone.

## Who has driven it

🧵 `sp.VirtioNetHost`; Zephyr's `drivers/ethernet/eth_virtio_net.c`, through `samples/net/sockets/echo_server`, which answers Python's ARP request and echoes its datagram; and EDK2's `VirtioNetDxe`, whose `ifconfig` shows the address and whose `ping` Python answers. ⚠️ With the network device in its slot, EDK2's boot manager tries PXE over IPv4 before its shell and waits about 65 s of simulated time for a DHCP answer nobody sends. 🐧 Linux's `virtio_net` (`VIRTIO_NET`, built in) makes it `eth0`, with the device's address: given an address at the prompt, Linux answers Python's ARP request and its ping (`tests/python/test_linux_boots.py`), which is M17's last line, on the stand-in before the real card. 🔌 Plugged into this machine's network by an [Ethernet cable](ethernet-cable.md), Linux takes its address by DHCP and answers `ssh` (`tests/python/test_ssh_over_the_cable.py`).
