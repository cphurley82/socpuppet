# The Zephyr that socpuppet's firmware is built with and tested against,
# and the SDK whose compiler builds it. Sourced by firmware/build.sh, which
# fetches both, and by firmware/twister.sh, which runs what was fetched.
# shellcheck shell=bash
# shellcheck disable=SC2034  # Used by the scripts that source this.
zephyr_version=v4.4.2
sdk_version=1.0.1
