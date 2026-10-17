#ifndef TESTS_CPP_CONTRACTS_VIRTIO_DEVICE_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_VIRTIO_DEVICE_CONTRACT_H_

#include <cstdint>
#include <functional>

#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/models/memory.h"
#include "socpuppet/platform/slots.h"
#include "socpuppet/regs/virtio_mmio.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/line_watcher.h"

// What a virtio device behind the virtio-mmio transport must do, whatever
// kind of device it is: the part every driver relies on before it knows
// what the device is. Linux's, Zephyr's and EDK2's drivers each start the
// same way: read the magic, agree on features, set up the queues, ring the
// doorbell, take the interrupt (virtio 1.2, sections 3 and 4.2).
//
// To hold an implementation to this contract:
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, VirtioDeviceContract,
//                                  ::testing::Types<MyDevice>);
// MyDevice must fit the virtio device slot (see socpuppet/platform/slots.h).
template <socpuppet::VirtioDeviceSlot DeviceType>
class VirtioDeviceContract : public ::testing::Test {
 protected:
  // The driver's memory: where the queues and the buffers are, behind the
  // device's DMA.
  static constexpr std::uint64_t kMemoryBase = 0x8000'0000;
  static constexpr std::size_t kMemorySize = 0x1'0000;

  VirtioDeviceContract() {
    device_.dma.bind(memory_.socket);
    device_.irq.bind(irq_);
    line_.line.bind(irq_);
  }

  // Runs `body` in a simulation thread wired to the device's registers.
  // The run ends when the body does.
  void OnTheBus(const std::function<void(BusDriver&)>& body) {
    BusDriver driver{"driver", [&](BusDriver& bus) {
                       body(bus);
                       sc_core::sc_stop();
                     }};
    driver.socket.bind(device_.cpu);
    sc_core::sc_start();
  }

  DeviceType device_{"device"};
  socpuppet::Memory memory_{"memory", kMemorySize};
  sc_core::sc_signal<bool> irq_{"irq"};
  LineWatcher line_{"line"};
};

TYPED_TEST_SUITE_P(VirtioDeviceContract);

TYPED_TEST_P(VirtioDeviceContract, WhenTheDriverLooksItSaysItIsAVirtioDevice) {
  this->OnTheBus([](BusDriver& bus) {
    // The bytes of `virt`, as a little-endian word.
    EXPECT_EQ(bus.Read32(VIRTIO_MMIO_MAGIC_VALUE), 0x74726976U);
    EXPECT_EQ(bus.Read32(VIRTIO_MMIO_VERSION), 2U);
  });
}

REGISTER_TYPED_TEST_SUITE_P(VirtioDeviceContract,
                            WhenTheDriverLooksItSaysItIsAVirtioDevice);

#endif  // TESTS_CPP_CONTRACTS_VIRTIO_DEVICE_CONTRACT_H_
