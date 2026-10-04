# Memory

`sp.Memory(size=...)` · C++ `socpuppet::Memory` · registry name `memory`

## What it stands for

A block of RAM: DRAM on a host, SRAM in a controller. It is a flat array of bytes on the bus.

## What it does

- **Reads and writes** through its TLM target socket. Addresses are offsets from the start of the memory; a router in front of it takes care of where it sits in the address map.
- **Address errors.** An access that runs past the end is answered with an address-error response and changes nothing.
- **DMI.** It grants direct memory access to the whole memory, read and write. 💡 This is what will let a CPU model run at full speed: after one request, the CPU reads and writes the bytes directly instead of making a transaction per access. Every bus access comes back with the DMI-allowed hint set, which is how a CPU model knows it is worth asking.
- **Debug transport.** `peek` and `poke` reach it without simulated time passing.

## What it leaves out

- **Timing.** Accesses take no simulated time. Real DRAM has latency, refresh and training; none of that is modeled.
- **Physical detail.** No ECC, no banks or ranks, no power states.
- **Initial contents.** It starts as all zeros. Real memory starts as garbage, and firmware that depends on zeros would get away with it here.
- **Read-only memory.** There is no ROM variant yet.

## Under the hood

The bytes live in `MemoryStore` (`src/socpuppet/core/memory_store.h`), a plain C++ class with bounds checks and no SystemC in it. `Memory` is the thin SystemC wrapper that turns transactions into calls on it.

Every memory implementation must pass `MemoryContract` (`tests/cpp/contracts/memory_contract.h`).
