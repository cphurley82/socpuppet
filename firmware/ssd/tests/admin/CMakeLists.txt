# A ztest suite for the admin commands of the SSD's firmware: the
# firmware's own admin.c and what it calls, built into a test in the
# firmware's place and run on the SSD's board by twister. See
# docs/twister.md.
cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(socpuppet_ssd_admin_test)

target_include_directories(app PRIVATE ../../src)
target_sources(app PRIVATE
  ../../src/admin.c
  ../../src/buffer.c
  ../../src/data.c
  ../../src/ftl.c
  ../../src/io.c
  src/main.c)
