#ifndef TESTS_CPP_SUPPORT_FAKE_PCIEM_DEVICE_H_
#define TESTS_CPP_SUPPORT_FAKE_PCIEM_DEVICE_H_

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <span>
#include <system_error>
#include <utility>
#include <vector>

#include "socpuppet/core/pciem_device.h"

// 🎭 This machine as a PciemHost's tests stand it in: what a test sets up
// and looks at, in place of the host's own Linux. The test keeps it, and
// the host is given a FakePciemDevice that works on it.
struct FakePciem {
  // The shape the host's device was opened in.
  socpuppet::PciemShape opened_as;
  // Whether the device has been put on the bus.
  bool started = false;
  // The descriptor the device says it has posted something on.
  int event_fd = -1;
  // The host's writes that pciem has posted and the device not yet
  // drained.
  std::vector<socpuppet::HostWrite> posted;
  // pciem's copy of BAR0, which is what the host reads, as big as the
  // shape the device was opened in says.
  std::vector<std::uint8_t> bar0;
  // The host's memory, from address 0, as the function's DMA reaches it.
  std::vector<std::uint8_t> memory = std::vector<std::uint8_t>(0x1000);
  // Whether the device refuses the function's DMA, as pciem does an
  // address the host never gave it.
  bool refuses_dma = false;
  // The interrupt vectors sent to the host, in the order they were sent.
  std::vector<unsigned> sent;
};

// A PciemDevice that works on a FakePciem, for a test to hand a PciemHost.
class FakePciemDevice : public socpuppet::PciemDevice {
 public:
  FakePciemDevice(FakePciem& machine, const socpuppet::PciemShape& shape)
      : machine_(machine) {
    machine_.opened_as = shape;
    machine_.bar0.assign(shape.function_size, 0);
  }

  void Dma(std::uint64_t address, std::span<std::uint8_t> data,
           bool to_host) override {
    if (machine_.refuses_dma) {
      throw std::system_error(std::make_error_code(std::errc::bad_address),
                              "DMA");
    }
    const auto there =
        machine_.memory.begin() + static_cast<std::ptrdiff_t>(address);
    if (to_host) {
      std::ranges::copy(data, there);
    } else {
      std::copy_n(there, data.size(), data.begin());
    }
  }

  void Start() override { machine_.started = true; }

  int EventFd() const override { return machine_.event_fd; }

  std::vector<socpuppet::HostWrite> Drain() override {
    return std::exchange(machine_.posted, {});
  }

  std::span<std::uint8_t> Bar0() override { return machine_.bar0; }

  void InjectIrq(unsigned vector) override { machine_.sent.push_back(vector); }

 private:
  FakePciem& machine_;
};

#endif  // TESTS_CPP_SUPPORT_FAKE_PCIEM_DEVICE_H_
