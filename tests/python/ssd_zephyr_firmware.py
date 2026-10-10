"""The SSD's own firmware, as a test runs it.

The image is `ssd_socpuppet_ssd.elf`: the Zephyr application in
`firmware/ssd`, built for the board `socpuppet_ssd`. It is the same image
on the SSD board and in the SSD under the host.
"""

IMAGE = "ssd_socpuppet_ssd.elf"
#: How the first line the firmware prints starts. The size of its drive
#: follows.
BANNER = "socpuppet SSD firmware: a drive of"
