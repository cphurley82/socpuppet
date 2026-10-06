#include <cstdint>
#include <string>

#include <gtest/gtest.h>

#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/registry.h"
#include "tests/cpp/contracts/nvme_contract.h"

namespace {

// The behavioral stand-in: one built-in component is the whole function.
struct BehavioralNvmeRig {
  static constexpr std::uint64_t kBlocks = 64;
  static constexpr unsigned kVectors = 2;

  static void Register(socpuppet::Registry&) {}
  static void Add(socpuppet::Platform& platform) {
    platform.Add("nvme", "behavioral_nvme",
                 {{"blocks", kBlocks}, {"vectors", kVectors}});
  }
  static const char* Registers() { return "nvme.bar0"; }
  static const char* Dma() { return "nvme.dma"; }
  static std::string Irq(unsigned vector) {
    return "nvme.irq" + std::to_string(vector);
  }
};

}  // namespace

INSTANTIATE_TYPED_TEST_SUITE_P(Behavioral, NvmeContract,
                               ::testing::Types<BehavioralNvmeRig>);
