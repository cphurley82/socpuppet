#ifndef TESTS_CPP_SUPPORT_FAKE_PCIEM_DEVICE_H_
#define TESTS_CPP_SUPPORT_FAKE_PCIEM_DEVICE_H_

#include <memory>

#include "socpuppet/core/pciem_device.h"

// 🎭 This machine as a PciemHost's tests stand it in: what a test sets up
// and looks at, in place of the host's own Linux. The test keeps it, and
// the host is given a FakePciemDevice that works on it.
struct FakePciem {
  // The shape the host's device was opened in.
  socpuppet::PciemShape opened_as;
};

// A PciemDevice that works on a FakePciem, for a test to hand a PciemHost.
class FakePciemDevice : public socpuppet::PciemDevice {
 public:
  explicit FakePciemDevice(FakePciem& machine) : machine_(machine) {}

 private:
  [[maybe_unused]] FakePciem& machine_;
};

#endif  // TESTS_CPP_SUPPORT_FAKE_PCIEM_DEVICE_H_
