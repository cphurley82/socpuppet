#ifndef TESTS_CPP_CONTRACTS_VIRTIO_DEVICE_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_VIRTIO_DEVICE_CONTRACT_H_

#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <span>
#include <utility>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/core/memory_port.h"
#include "socpuppet/core/virtqueue.h"
#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/registry.h"
#include "socpuppet/platform/slots.h"
#include "socpuppet/regs/virtio_mmio.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/line_watcher.h"
#include "tests/cpp/support/test_components.h"
#include "tests/cpp/support/virtqueue_driver.h"

// What a virtio device behind the virtio-mmio transport must do, whatever
// kind of device it is: the part every driver relies on before it knows
// what the device is. Linux's, Zephyr's and EDK2's drivers each start the
// same way: read the magic, agree on features, set up a queue, ring the
// doorbell, take the interrupt (virtio 1.2, sections 3 and 4.2).
//
// To hold an implementation to this contract:
//   struct MyRig {
//     using Device = MyDevice;  // fits the virtio device slot (slots.h)
//     // Describes, on queue 0, a chain this kind of device answers at
//     // once, and makes it available.
//     static void AChainItAnswers(VirtqueueDriver& driver);
//   };
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, VirtioDeviceContract,
//                                  ::testing::Types<MyRig>);
template <typename Rig>
class VirtioDeviceContract : public ::testing::Test {
  static_assert(socpuppet::VirtioDeviceSlot<typename Rig::Device>,
                "The rig's device must fit the virtio device slot.");

 protected:
  // Where the driver's bus has the device's registers, and where it has
  // its own memory, which the device reaches too.
  static constexpr std::uint64_t kRegisters = 0x1000'1000;
  static constexpr std::uint64_t kMemoryBase = 0x8000'0000;
  static constexpr std::size_t kMemorySize = 0x1'0000;
  // The driver's one queue, of eight entries, and its buffers after it.
  static constexpr socpuppet::Virtqueue::Layout kQueue{
      .desc = kMemoryBase + 0x1000,
      .avail = kMemoryBase + 0x2000,
      .used = kMemoryBase + 0x3000,
      .size = 8};
  static constexpr std::uint64_t kBuffers = kMemoryBase + 0x4000;
  // Long enough for a device that has been rung to answer.
  static sc_core::sc_time Patience() { return {1, sc_core::SC_US}; }

  // The driver's memory, as the driver itself reaches it: over the bus.
  class OverTheBus : public socpuppet::MemoryPort {
   public:
    explicit OverTheBus(BusDriver& bus) : bus_(bus) {}
    bool Read(std::uint64_t address, std::span<std::uint8_t> out) override {
      return bus_.Read(address, out) == tlm::TLM_OK_RESPONSE;
    }
    bool Write(std::uint64_t address,
               std::span<const std::uint8_t> in) override {
      return bus_.Write(address, in) == tlm::TLM_OK_RESPONSE;
    }

   private:
    BusDriver& bus_;
  };

  // What the driver has in hand once it is on the bus.
  struct Driver {
    BusDriver& bus;
    OverTheBus memory{bus};
    VirtqueueDriver queue{memory, kQueue, kBuffers};

    std::uint32_t Read32(std::uint64_t offset) {
      return bus.Read32(kRegisters + offset);
    }
    void Write32(std::uint64_t offset, std::uint32_t value) {
      EXPECT_EQ(bus.Write32(kRegisters + offset, value), tlm::TLM_OK_RESPONSE);
    }

    // Sets queue 0 up and tells the device the driver is ready, the way
    // every driver does.
    void SetUp() {
      Write32(VIRTIO_MMIO_STATUS,
              VIRTIO_MMIO_STATUS_ACKNOWLEDGE | VIRTIO_MMIO_STATUS_DRIVER);
      Write32(VIRTIO_MMIO_QUEUE_SEL, 0);
      Write32(VIRTIO_MMIO_QUEUE_NUM, kQueue.size);
      Write32(VIRTIO_MMIO_QUEUE_DESC_LOW,
              static_cast<std::uint32_t>(kQueue.desc));
      Write32(VIRTIO_MMIO_QUEUE_DESC_HIGH,
              static_cast<std::uint32_t>(kQueue.desc >> 32));
      Write32(VIRTIO_MMIO_QUEUE_DRIVER_LOW,
              static_cast<std::uint32_t>(kQueue.avail));
      Write32(VIRTIO_MMIO_QUEUE_DRIVER_HIGH,
              static_cast<std::uint32_t>(kQueue.avail >> 32));
      Write32(VIRTIO_MMIO_QUEUE_DEVICE_LOW,
              static_cast<std::uint32_t>(kQueue.used));
      Write32(VIRTIO_MMIO_QUEUE_DEVICE_HIGH,
              static_cast<std::uint32_t>(kQueue.used >> 32));
      Write32(VIRTIO_MMIO_QUEUE_READY, VIRTIO_MMIO_QUEUE_READY_READY);
      Write32(VIRTIO_MMIO_STATUS, VIRTIO_MMIO_STATUS_ACKNOWLEDGE |
                                      VIRTIO_MMIO_STATUS_DRIVER |
                                      VIRTIO_MMIO_STATUS_DRIVER_OK);
    }

    // Puts a chain the device answers on queue 0 and rings its doorbell.
    void Ask() {
      Rig::AChainItAnswers(queue);
      Write32(VIRTIO_MMIO_QUEUE_NOTIFY, 0);
    }
  };

  // Builds the platform and runs it with `body` as what the driver does.
  // The run ends when the driver has done it.
  void OnTheBus(const std::function<void(Driver&, LineWatcher&)>& body) {
    socpuppet::Registry registry = socpuppet::BuiltinComponents();
    registry.Add("device", [](const char* name, socpuppet::Parameters&) {
      auto module = std::make_unique<typename Rig::Device>(name);
      std::vector<socpuppet::Port> ports{
          socpuppet::TargetPort("cpu", module->cpu),
          socpuppet::InitiatorPort("dma", module->dma),
          socpuppet::WireSourcePort("irq", module->irq)};
      return socpuppet::Instance{.module = std::move(module),
                                 .ports = std::move(ports)};
    });
    AddBusDriver(registry, "driver", [this, body](BusDriver& bus) {
      Driver driver{bus};
      body(driver, *line_);
      sc_core::sc_pause();
    });
    AddLineWatcher(registry, "line_watcher");
    platform_ = std::make_unique<socpuppet::Platform>(std::move(registry));
    platform_->Add("driver", "driver");
    platform_->Add("bus", "router",
                   {{"inputs", 2},
                    {"outputs", 2},
                    {"out0.base", kMemoryBase},
                    {"out0.size", kMemorySize},
                    {"out1.base", kRegisters},
                    {"out1.size", VIRTIO_MMIO_SIZE}});
    platform_->Add("memory", "memory", {{"size", kMemorySize}});
    platform_->Add("device", "device");
    platform_->Add("line", "line_watcher");
    platform_->Bind("driver.socket", "bus.target");
    platform_->Bind("bus.out0", "memory.socket");
    platform_->Bind("bus.out1", "device.cpu");
    platform_->Bind("device.dma", "bus.in1");
    platform_->Bind("device.irq", "line.line");
    platform_->Elaborate();
    line_ = &platform_->template ModuleAt<LineWatcher>("line");
    platform_->Run();
  }

  std::unique_ptr<socpuppet::Platform> platform_;
  LineWatcher* line_ = nullptr;
};

TYPED_TEST_SUITE_P(VirtioDeviceContract);

TYPED_TEST_P(VirtioDeviceContract, WhenTheDriverLooksItSaysItIsAVirtioDevice) {
  this->OnTheBus([](auto& driver, LineWatcher&) {
    // The bytes of `virt`, as a little-endian word.
    EXPECT_EQ(driver.Read32(VIRTIO_MMIO_MAGIC_VALUE), 0x74726976U);
    EXPECT_EQ(driver.Read32(VIRTIO_MMIO_VERSION), 2U);
  });
}

TYPED_TEST_P(
    VirtioDeviceContract,
    WhenTheDriverRingsTheDoorbellWithAChainTheDeviceAnswers_ItIsGivenBackUsedAndTheLineRises) {
  this->OnTheBus([this](auto& driver, LineWatcher& line) {
    driver.SetUp();

    driver.Ask();

    EXPECT_TRUE(line.WaitForLevel(true, this->Patience()));
    EXPECT_EQ(driver.queue.UsedIndex(), 1);
  });
}

TYPED_TEST_P(VirtioDeviceContract,
             WhenTheDriverAcknowledgesTheInterrupt_TheLineFalls) {
  this->OnTheBus([this](auto& driver, LineWatcher& line) {
    driver.SetUp();
    driver.Ask();
    ASSERT_TRUE(line.WaitForLevel(true, this->Patience()));

    driver.Write32(VIRTIO_MMIO_INTERRUPT_ACK,
                   driver.Read32(VIRTIO_MMIO_INTERRUPT_STATUS));

    EXPECT_TRUE(line.WaitForLevel(false, this->Patience()));
  });
}

TYPED_TEST_P(VirtioDeviceContract,
             WhenTheDriverRingsAgainAfterAcknowledging_TheLineRisesAgain) {
  this->OnTheBus([this](auto& driver, LineWatcher& line) {
    driver.SetUp();
    driver.Ask();
    ASSERT_TRUE(line.WaitForLevel(true, this->Patience()));
    driver.Write32(VIRTIO_MMIO_INTERRUPT_ACK,
                   driver.Read32(VIRTIO_MMIO_INTERRUPT_STATUS));
    ASSERT_TRUE(line.WaitForLevel(false, this->Patience()));

    driver.Ask();

    EXPECT_TRUE(line.WaitForLevel(true, this->Patience()));
    EXPECT_EQ(driver.queue.UsedIndex(), 2);
  });
}

TYPED_TEST_P(VirtioDeviceContract,
             WhenTheDriverResetsTheDevice_TheLineFallsAndTheQueueIsGone) {
  this->OnTheBus([this](auto& driver, LineWatcher& line) {
    driver.SetUp();
    driver.Ask();
    ASSERT_TRUE(line.WaitForLevel(true, this->Patience()));

    driver.Write32(VIRTIO_MMIO_STATUS, 0);

    EXPECT_TRUE(line.WaitForLevel(false, this->Patience()));
    driver.Write32(VIRTIO_MMIO_QUEUE_SEL, 0);
    EXPECT_EQ(driver.Read32(VIRTIO_MMIO_QUEUE_READY), 0U);
  });
}

TYPED_TEST_P(
    VirtioDeviceContract,
    WhenTheDriversDoorbellWriteReturns_TheDeviceHasNotYetTouchedTheMemory) {
  this->OnTheBus([this](auto& driver, LineWatcher& line) {
    driver.SetUp();

    driver.Ask();
    const std::uint16_t as_the_write_returns = driver.queue.UsedIndex();

    EXPECT_EQ(as_the_write_returns, 0);
    EXPECT_TRUE(line.WaitForLevel(true, this->Patience()));
    EXPECT_EQ(driver.queue.UsedIndex(), 1);
  });
}

REGISTER_TYPED_TEST_SUITE_P(
    VirtioDeviceContract, WhenTheDriverLooksItSaysItIsAVirtioDevice,
    WhenTheDriverRingsTheDoorbellWithAChainTheDeviceAnswers_ItIsGivenBackUsedAndTheLineRises,
    WhenTheDriverAcknowledgesTheInterrupt_TheLineFalls,
    WhenTheDriverRingsAgainAfterAcknowledging_TheLineRisesAgain,
    WhenTheDriverResetsTheDevice_TheLineFallsAndTheQueueIsGone,
    WhenTheDriversDoorbellWriteReturns_TheDeviceHasNotYetTouchedTheMemory);

#endif  // TESTS_CPP_CONTRACTS_VIRTIO_DEVICE_CONTRACT_H_
