#ifndef TESTS_CPP_SUPPORT_THE_CPU_H_
#define TESTS_CPP_SUPPORT_THE_CPU_H_

#include <cstdlib>
#include <string>

#include "socpuppet/platform/platform.h"

// The CPU the hart's tests run on: the registry's name for it, from
// SOCPUPPET_CPU, and "dbt_rise_cpu" when that is not set. The `qbox` test
// preset (CMakePresets.json) sets it to "qbox_cpu".
inline std::string TheCpu() {
  // NOLINTNEXTLINE(concurrency-mt-unsafe): read before any thread exists.
  const char* cpu = std::getenv("SOCPUPPET_CPU");
  return cpu != nullptr ? cpu : "dbt_rise_cpu";
}

// Adds the CPU the tests run on at `path`. `config` is a dbt_rise_cpu's,
// whose cores come with or without floating point and supervisor mode.
// QBox's one core has both, so it is not asked.
inline void AddTheCpu(socpuppet::Platform& platform, const std::string& path,
                      socpuppet::Config config) {
  if (TheCpu() == "qbox_cpu") {
    config.erase("floating_point");
    config.erase("supervisor_mode");
  }
  platform.Add(path, TheCpu(), config);
}

#endif  // TESTS_CPP_SUPPORT_THE_CPU_H_
