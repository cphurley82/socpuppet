# The AIA spike 🚧

Step 0 of milestone M13, which gives the host an IMSIC and an APLIC where it has a PLIC ([docs/plan.md](../../docs/plan.md)). Zephyr 4.4.2 has a driver for each and no board in its tree that uses either, so nobody had seen them build for a board, let alone socpuppet's.

**The question.** Does Zephyr build for a `socpuppet_host` whose devicetree has `riscv,imsic` under `smcsrind` and no PLIC, and what does socpuppet's Zephyr module have to supply around the two drivers?

**The answer.** Yes, with glue and nothing more. `hello_world`, the disk test with the drive's shield, and the shell sample all build. Nothing was simulated: the models these images need do not exist yet, and building them is what M13's steps are.

⚠️ Nothing here is part of socpuppet. It is exploratory code, nothing outside `spikes/` may depend on it, and it goes when M13's step 8 puts the real thing in the module.

## Running it

```sh
firmware/build.sh      # once: leaves the toolchain and Zephyr in build/firmware
spikes/aia/build.sh    # builds the three images in build/spikes/aia
```

The trial module is socpuppet's own (`python/socpuppet/zephyr_module`) with this directory's `module/` laid over it. Each file in `module/` is the real one with the spike's change made, so `diff -r` of the two shows the whole of it.

## What it found

**What switches the drivers on.** A `riscv,imsic` node and `smcsrind` in the CPU's `riscv,isa-extensions` are enough for `CONFIG_RISCV_IMSIC`. A `riscv,aplic` node with `msi-parent` gives `CONFIG_RISCV_APLIC_MSI`. With no PLIC selected, `CONFIG_MULTI_LEVEL_INTERRUPTS` is off, and an interrupt's number in the devicetree is the number firmware uses.

**The SoC's Kconfig.** The family selected `RISCV_HAS_PLIC` for every SoC. It now selects it `if DT_HAS_SIFIVE_PLIC_1_0_0_ENABLED`, so the devicetree decides, and the 32-bit kits keep theirs with no word changed. The second-level numbers move inside `if RISCV_HAS_PLIC`, and `NUM_IRQS` is 64 `if RISCV_IMSIC`.

**One space of numbers.** Zephyr's IMSIC driver takes an identity as the interrupt's number and looks it up in the same table as the CPU's own lines. So the spike's rule is:

| Numbers | What |
|---|---|
| 0 to 15 | The CPU's own lines: 7 is the timer, 11 is the IMSIC's. |
| 16 to 31 | An APLIC source, sent as the identity of the same number. |
| 32 to 62 | Identities for messages from anywhere else. The drive's two are 32 and 33. |

⚠️ Identity 63 is lost: the driver refuses `irq >= MIN(riscv,num-ids, NUM_IRQS)`, and `riscv,num-ids` is the highest identity, not one more than it.

**`irq_enable` needs glue, and the linker's `--wrap` is it.** Zephyr's `arch_irq_enable` for RISC-V sets bit `irq` of `mie` unless a PLIC or a CLIC is configured, and the file is compiled for every SoC with the privileged architecture, so the module cannot define the function again. `module/drivers/interrupt_controller/aia_irq.c` defines `__wrap_arch_irq_enable` and its two friends, and the module's CMake passes `-Wl,--wrap=`. In the built images every caller jumps to the wrapper: the timer's 7 and the IMSIC's 11 go on to Zephyr's own, an identity is enabled in the IMSIC, and an APLIC source is also given its mode, routed to its identity and enabled. The other candidate, a `SYS_INIT` that enables everything the devicetree names, was not needed.

**The root complex's driver** takes its identities from a property of ours on its node, `socpuppet,msi-identities = <32 33>`, and gives each vector the IMSIC's page as its address and the identity as its data. Zephyr's PCIe code then calls `irq_enable` on the identity, which the glue answers.

**The UART's interrupt has to be spelled `interrupts`.** The 16550 driver says it can interrupt only if a node has a property of that name (`dt_compat_any_has_prop`), and `interrupts-extended`, which is what socpuppet's generator writes everywhere, is another name. So the UART's node gets `interrupt-parent` and `interrupts`.

⚠️ **A shell does not need the interrupt to answer.** Without `CONFIG_UART_INTERRUPT_DRIVEN` the shell asks the UART every 10 ms, and an exit test that only looked for the answer would pass with the UART's line cut. The spike puts the option in the board's defconfig, which gives `CONFIG_SHELL_BACKEND_SERIAL_API_INTERRUPT_DRIVEN`, and M13's exit test has to see the message.

**`f` and `d` in the ISA list change nothing in the images.** `CONFIG_FPU` stays off, the ABI stays soft-float, and no floating-point instruction is emitted.

**What the models will be asked**, read out of the images and the drivers:

- The IMSIC is reached with `csrw miselect`, then `csrr`, `csrs` or `csrwi` on `mireg`, and claimed with `csrrwi mtopei, 0`. So `mireg` must answer a read and a write, and `mtopei` a read with a write. Zephyr takes the identity from the low 11 bits of `mtopei`.
- `eidelivery` is written 1 and `eithreshold` 0.
- ⚠️ The APLIC's driver never sets `domaincfg.DM`, whatever its comment says: it sets `IE` and leaves the delivery mode "as configured by platform". The model has to be in MSI mode without being told.
- It writes `mmsiaddrcfg` only if both halves read zero, with the IMSIC's page number.
- It sets bit 11 of `target`, which the specification reserves.

## What building could not say

- **Whether the two drivers work.** They have compiled. They have not run.
- ⚠️ **A wire that stays high.** In MSI mode an APLIC sends a level-sensitive source's message once, when the line rises. Linux pends it again after each interrupt if the line is still high, and Zephyr does not. A UART whose line stays high from one interrupt into the next, as it may while it has more to transmit, would then go quiet. M13's step 13 will see.
- **A build directory keeps its configuration.** A change to the board's defconfig did not reach a directory that already existed, so `build.sh` starts each from nothing.
