#include <string>

#include <gtest/gtest.h>

#include "socpuppet/models/pass_through_link.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/registry.h"
#include "tests/cpp/contracts/link_contract.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/ucie_link_driving.h"

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
  static std::string Control(const char*) { return ""; }
  static void BringUp(BusDriver&) {}
  static void WaitUntilUp(BusDriver&) {}

 private:
  static std::string Endpoint(const char* die) {
    return std::string(die) + ".link";
  }
};

INSTANTIATE_TYPED_TEST_SUITE_P(PassThrough, LinkContract,
                               ::testing::Types<PassThroughRig>);

// The real link has to be trained before it carries anything, which die A
// does through its registers while die B waits for it.
struct D2dRig {
  static void Register(socpuppet::Registry&) {}

  static void Add(socpuppet::Platform& platform) {
    for (const char* die : {kDieA, kDieB}) {
      platform.Add(Endpoint(die), "d2d_link_endpoint",
                   {{"training_ns", kTrainingNs}});
    }
    platform.Bind(Endpoint(kDieA) + ".peer_initiator",
                  Endpoint(kDieB) + ".peer_target");
    platform.Bind(Endpoint(kDieB) + ".peer_initiator",
                  Endpoint(kDieA) + ".peer_target");
    platform.Bind(Endpoint(kDieA) + ".sideband_peer_initiator",
                  Endpoint(kDieB) + ".sideband_peer_target");
    platform.Bind(Endpoint(kDieB) + ".sideband_peer_initiator",
                  Endpoint(kDieA) + ".sideband_peer_target");
  }

  static std::string Target(const char* die) {
    return Endpoint(die) + ".target";
  }
  static std::string Initiator(const char* die) {
    return Endpoint(die) + ".initiator";
  }
  static std::string Control(const char* die) {
    return Endpoint(die) + ".sideband";
  }
  static void BringUp(BusDriver& bus) { BringTheLinkUp(bus, kLinkControlBase); }
  static void WaitUntilUp(BusDriver& bus) {
    WaitUntilTheLinkIsUp(bus, kLinkControlBase);
  }

 private:
  // Training takes a tenth of a millisecond here, on top of UCIe's 4 ms
  // reset hold: the contract is about what crosses the link, not how long
  // it takes to come up.
  static constexpr std::uint64_t kTrainingNs = 100'000;

  static std::string Endpoint(const char* die) {
    return std::string(die) + ".link";
  }
};

INSTANTIATE_TYPED_TEST_SUITE_P(D2d, LinkContract, ::testing::Types<D2dRig>);

}  // namespace
