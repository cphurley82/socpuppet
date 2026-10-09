#include <string>

#include <gtest/gtest.h>

#include "socpuppet/models/pass_through_link.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/registry.h"
#include "tests/cpp/contracts/link_contract.h"
#include "tests/cpp/support/bus_driver.h"

namespace {

// 🎭 The pass-through link is always up, so there is nothing to bring up
// and no registers to bring it up through.
struct PassThroughRig {
  static void Register(socpuppet::Registry&) {}

  static void Add(socpuppet::Platform& platform) {
    platform.Add(Endpoint(kDieA), "pass_through_link_endpoint");
    platform.Add(Endpoint(kDieB), "pass_through_link_endpoint");
    platform.Bind(Endpoint(kDieA) + ".peer_initiator",
                  Endpoint(kDieB) + ".peer_target");
    platform.Bind(Endpoint(kDieB) + ".peer_initiator",
                  Endpoint(kDieA) + ".peer_target");
  }

  static std::string Target(const char* die) {
    return Endpoint(die) + ".target";
  }
  static std::string Initiator(const char* die) {
    return Endpoint(die) + ".initiator";
  }
  static void BringUp(BusDriver&) {}
  static void WaitUntilUp(BusDriver&) {}

 private:
  static std::string Endpoint(const char* die) {
    return std::string(die) + ".link";
  }
};

INSTANTIATE_TYPED_TEST_SUITE_P(PassThrough, LinkContract,
                               ::testing::Types<PassThroughRig>);

}  // namespace
