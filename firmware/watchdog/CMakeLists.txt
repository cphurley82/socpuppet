# A firmware that gets itself reset twice, to show a system controller and
# a watchdog at work: a Zephyr application for any socpuppet board. See
# README.md beside this file.
cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(socpuppet_watchdog_firmware)

target_sources(app PRIVATE src/main.c)
