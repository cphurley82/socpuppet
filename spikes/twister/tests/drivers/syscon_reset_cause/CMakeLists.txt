# Question 5 of the spike: a ztest suite kept beside socpuppet's drivers,
# found and run by twister.
cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(socpuppet_syscon_reset_cause)
target_sources(app PRIVATE src/main.c)
