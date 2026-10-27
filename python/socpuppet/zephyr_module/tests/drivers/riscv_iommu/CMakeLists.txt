# A ztest suite for one driver or device of socpuppet's Zephyr module,
# found and run by twister. See ../../README.md.
cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(socpuppet_riscv_iommu_test)

target_sources(app PRIVATE src/main.c)
