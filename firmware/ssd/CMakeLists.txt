# The firmware of socpuppet's SSD: a Zephyr application for the board
# socpuppet_ssd. See README.md beside this file.
cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(socpuppet_ssd_firmware)

target_sources(app PRIVATE
  src/admin.c
  src/buffer.c
  src/data.c
  src/ftl.c
  src/io.c
  src/main.c)
