"""The register maps of socpuppet's own blocks, as Python.

One module for each block: where each of its registers is, what its bits
are, and what it can be told. They are for the stand-ins, which drive a
block as its firmware would, and for the components, which say how big a
block is.

⚠️ The modules are generated, by `tools/regs.py` in socpuppet's repo, from
the SystemRDL files in `regs/` there. The Zephyr drivers get the same
numbers from the headers in `zephyr_module/include/socpuppet/regs`, and
the models get them from those headers too.
"""
