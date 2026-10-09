# 🎭 Ideal NAND

`sp.IdealNand(blocks=..., pages_per_block=64, page_size=4096)` · C++ `socpuppet::IdealNand` · registry name `ideal_nand`

## What it stands in for

A NAND flash chip, which is what an SSD keeps its data in.

🎓 NAND flash is not written the way memory is. It has three operations, and they come in two sizes:

```text
 one block
 ┌──────────┬──────────┬──────────┬─  ─┬──────────┐
 │  page 0  │  page 1  │  page 2  │ …  │ page 63  │   read:    one page
 └──────────┴──────────┴──────────┴─  ─┴──────────┘   program: one page
 └──────────────────── erase: the whole block ────┘
```

- A **page** is what is read and what is programmed, a few kilobytes at a time. "Program" is NAND's word for write.
- A **block** is many pages, and it is what is erased. Erasing sets every bit of every page in it to one.
- Programming can only turn ones into zeros. So a page that holds something cannot simply be given something new: its whole block has to be erased first, and the other pages of the block go with it.

That last rule is why an SSD needs firmware at all. Something has to keep track of where each of the drive's blocks really is, write a changed one somewhere fresh, and tidy up afterwards. That something is the flash translation layer (FTL).

🎭 This model is a stand-in for the chip. It has the pages, the blocks and the three operations, so a flash controller and an FTL can rehearse against it, but it is far easier to live with than the real thing: nothing takes any time, and a page can be programmed again without erasing its block. The realistic chip is a later milestone, and it will be held to the same contract.

## What it does

```python
nand = ssd.add("nand", sp.IdealNand(blocks=64))
platform.connect(flash.nand, nand.socket)       # a flash controller's way to it
```

It has one port, `socket`, and it is not memory: it has no addresses to read and write. What arrives at it is a command, which says which operation and which page.

| Operation | What it does |
|---|---|
| read a page | gives back what the page holds. A page nothing was ever programmed into reads as all ones. |
| program a page | puts a page's worth of data into it. |
| erase a block | makes every page of the block read as all ones again. |
| geometry | says what the chip is: the page size, the pages in a block, and how many blocks. 🎓 A real chip has a *parameter page* that says the same. |

- **Only what has been programmed takes memory**, so a chip can be far larger than the machine you run on.
- **What it refuses**: a block it does not have, a page past the end of its block, data that is not exactly one page long, and an access that is not a command for a chip at all, which is what arrives if a chip is wired to a bus by mistake.
- **A debugger cannot look inside.** `peek` gets no answer, because an address means nothing to it.

## What it leaves out

- **Time.** A real read takes tens of microseconds, a program hundreds, and an erase milliseconds. Here all three are immediate.
- **Erase before program.** A page here can be programmed twice, and the second time it simply holds the new data. On a real chip that gives the AND of the two, which is rarely what anyone wanted.
- **Wear, bad blocks and bit errors.** A real block survives only so many erases, some are bad from the factory, and bits flip, which is why real pages carry spare bytes for an error-correcting code. None of it is here.
- **The pins.** A real chip is told what to do by command, address and data cycles on a shared set of pins. What a controller's firmware can observe of that is which operation was asked for, of which page, and how it came out, and that is what is kept.
- **More than one chip, or planes within one.**

## Under the hood

- `src/socpuppet/core/nand_array.h` is the cells: pages kept by block, with no simulator in them.
- `src/socpuppet/models/nand_link.h` is how a controller and a chip talk. 🎓 TLM lets a transaction carry extra information as an *extension*, and every transaction to a chip carries one saying which operation, which block and which page. The transaction's data is the page.
- `src/socpuppet/models/ideal_nand.h` is the SystemC wrapper, which turns the chip's answers into TLM responses: an address error for a page it does not have, a burst error for data of the wrong length, a command error for an access with no command.
- Every NAND chip must pass `NandContract` (`tests/cpp/contracts/nand_contract.h`).
