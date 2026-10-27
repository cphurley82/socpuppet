# The docs 🧦

The map of socpuppet's documentation. Start where you stand; every page says what it is for in its first line.

## 🌱 Never seen a chip from the inside?

Start with the [README](../README.md): it runs a whole chip's boot in a dozen lines of Python, and then a smaller show with no CPU at all. Then 🧪 [the labs](labs/README.md), sessions of commands to run with a line under each saying what to look at. 🚧 A page that needs nothing but Python is on the list for the first release ([vision.md](vision.md), the release gate).

## 🎓 Learning how a chip boots, or building a first virtual platform

- 🧪 [The labs](labs/README.md): sessions at the keyboard, the first of them [Linux end to end](labs/linux-tour.md): boot it, `ssh` in, swap the CPU and the 🎭 stand-ins, and poke at the logs and a debugger.
- [How socpuppet is put together](architecture.md): the parts, the words used for them (TLM, DMI, the quantum), and why they are shaped the way they are. Its list of models links to a page for each block, which says what real hardware it stands for and what it leaves out.
- [A PCIe device and its hosts](pcie.md): how a device is modelled, how PCIe lands on SystemC and Python pulls its strings, with the host played in the simulation or by 🐧 this machine's own Linux through pciem, and a command to run each.
- [Why socpuppet exists](vision.md): who it is for, the aims, and how choices get made.
- [The address map](address-map.md): what answers at which address, on each board, generated from the boards themselves.
- [How it got here](history/README.md): the decisions and their reasons, the lessons, and the spike reports.

## 🧵 Bringing your own firmware

- [Boot your firmware here](boot-your-firmware.md): from a fresh checkout to Zephyr's hello world on the host, then your own application, typing on the console, and a debugger.
- [The boards, and the bigger shows](boards.md): the SSD's controller and the IO die's manager, the host with the SSD and across the link, all three firmwares at once, booting from flash, OpenSBI, UEFI, Linux, and the watchdog.
- [Run Zephyr's tests on the puppet](twister.md): Zephyr's own suites, and yours, on every board.
- [Booting Linux](linux.md): 🐧 a stock kernel on OpenSBI, with your terminal at its shell (`socpuppet linux`) or Python typing at it, the virtio cast, a shared directory, and what to do when it does not boot.

## 🔧 Working on socpuppet

- [Setting up a machine](setup.md): from a bare install to every test passing, QBox and pciem included.
- [Building and testing](development.md): the everyday loop, the tests, coverage, sanitizers, CI's jobs, the firmware, the package.
- [Style, and the tools that hold us to it](style.md).
- [What we owe upstream](upstream.md): every fix we carry for the projects we borrow from, ready to send.
- [The roadmap](roadmap.md): phases, milestones, what is next, open decisions and loose ends.
