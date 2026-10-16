# The Zephyr that socpuppet's firmware is built with and tested against,
# the SDK whose compiler builds it, the OpenSBI the host boots Linux's way
# with, and the EDK2 that boots on it as UEFI. Sourced by firmware/build.sh,
# which fetches all four, and by
# firmware/twister.sh, which runs the Zephyr and the SDK it fetched. CI
# keeps twister's copy of those under a key made of this whole file, so a
# new OpenSBI or EDK2 has twister fetch them once more, which is the price of one
# list of versions.
# shellcheck shell=bash
# shellcheck disable=SC2034  # Used by the scripts that source this.
zephyr_version=v4.4.2
sdk_version=1.0.1
opensbi_version=v1.9
edk2_version=edk2-stable202608
