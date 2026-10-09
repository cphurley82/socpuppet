# Zephyr's own test of a flash driver, built for the board socpuppet_ssd,
# where the flash is the SSD's NAND behind its flash controller. See
# README.md beside this file.
cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(socpuppet_flash_test)

# The test itself is Zephyr's, as it is.
target_sources(app PRIVATE
  $ENV{ZEPHYR_BASE}/tests/drivers/flash/common/src/main.c)
