#ifndef TESTS_CPP_CONTRACTS_SPI_CONTROLLER_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_SPI_CONTROLLER_CONTRACT_H_

#include <array>
#include <cstdint>
#include <functional>
#include <optional>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/core/spi_device.h"
#include "socpuppet/platform/slots.h"
#include "tests/cpp/support/bus_driver.h"

// What an SPI controller with the registers of SiFive's (the one in the
// FE310 and the FU540) must do, whatever is behind it. This is the part
// that Zephyr's `spi_sifive` driver and Linux's `spi-sifive` rely on.
//
// 🎓 A controller of this kind moves bytes, not bits: firmware puts a byte
// in its transmit FIFO, the controller clocks it out to the selected chip
// while the chip's answer clocks in, and the answer lands in the receive
// FIFO. Which chip is selected is a chip select id, and when its line is
// pulled low is the chip select mode.
//
// To hold an implementation to this contract:
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, SpiControllerContract,
//                                  ::testing::Types<MyController>);
// MyController must fit the SPI controller slot (see
// socpuppet/platform/slots.h).
template <socpuppet::SpiControllerSlot ControllerType>
class SpiControllerContract : public ::testing::Test {
 protected:
  // The registers, 32 bits each.
  static constexpr std::uint64_t kChipSelectId = 0x10;
  static constexpr std::uint64_t kChipSelectMode = 0x18;
  static constexpr std::uint64_t kTransmit = 0x48;
  static constexpr std::uint64_t kReceive = 0x4C;

  // The chip select modes: hold the selected chip's line low from the
  // first byte until the mode changes.
  static constexpr std::uint32_t kHold = 2;
  // Drive no chip select line at all.
  static constexpr std::uint32_t kOff = 3;
  // Set in the receive register when the receive FIFO had nothing in it.
  static constexpr std::uint32_t kReceiveEmpty = 1U << 31;

  // A chip on the bus that keeps everything it is sent, and answers every
  // byte with the same one. A frame is the bytes between its select and
  // its deselect.
  struct RecordingChip : socpuppet::SpiDevice {
    void Select() override { frame_.emplace(); }
    std::uint8_t Transfer(std::uint8_t sent) override {
      received.push_back(sent);
      if (frame_) frame_->push_back(sent);
      return answer;
    }
    void Deselect() override {
      if (frame_) frames.push_back(*frame_);
      frame_.reset();
    }

    std::uint8_t answer = 0;
    std::vector<std::uint8_t> received;
    // Every frame that has ended.
    std::vector<std::vector<std::uint8_t>> frames;

   private:
    std::optional<std::vector<std::uint8_t>> frame_;
  };

  SpiControllerContract() {
    controller_.irq.bind(irq_);
    for (unsigned chip_select = 0; chip_select < chips_.size(); ++chip_select) {
      controller_.Attach(chip_select, chips_[chip_select]);
    }
  }

  // Runs `body` in a simulation thread wired to the controller.
  void OnTheBus(const std::function<void(BusDriver&)>& body) {
    BusDriver driver{"driver", [&](BusDriver& bus) {
                       body(bus);
                       sc_core::sc_stop();
                     }};
    driver.socket.bind(controller_.socket);
    sc_core::sc_start();
  }

  // Selects the chip at `chip_select` the way Zephyr's driver does: its id,
  // then its line held low from the first byte until the mode changes.
  static void Select(BusDriver& bus, unsigned chip_select) {
    bus.Write32(kChipSelectId, chip_select);
    bus.Write32(kChipSelectMode, kHold);
  }

  // Lets the selected chip go, as Zephyr's driver does at the end of a
  // transfer: no chip select line is driven.
  static void LetGo(BusDriver& bus) { bus.Write32(kChipSelectMode, kOff); }

  // Sends one byte and returns what came back, the way Zephyr's driver
  // does: the byte into the transmit FIFO, then a look at the receive FIFO
  // until a byte is there. Nothing, if none comes within a millisecond,
  // far longer than a byte takes at any clock this contract uses.
  static std::optional<std::uint8_t> Send(BusDriver& bus, std::uint8_t byte) {
    bus.Write32(kTransmit, byte);
    const sc_core::sc_time give_up =
        sc_core::sc_time_stamp() + sc_core::sc_time{1, sc_core::SC_MS};
    while (sc_core::sc_time_stamp() < give_up) {
      const std::uint32_t received = bus.Read32(kReceive);
      if ((received & kReceiveEmpty) == 0) {
        return static_cast<std::uint8_t>(received);
      }
      // A driver's look takes time on a real bus; here it has to be made
      // to, or simulated time would never move on to the byte's arrival.
      bus.WaitFor(sc_core::sc_time{100, sc_core::SC_NS});
    }
    return std::nullopt;
  }

  // Two chips, at chip selects 0 and 1. Chip selects 2 and 3 have none.
  std::array<RecordingChip, 2> chips_;
  ControllerType controller_{"controller"};
  sc_core::sc_signal<bool> irq_{"irq"};
};

TYPED_TEST_SUITE_P(SpiControllerContract);

TYPED_TEST_P(SpiControllerContract, AByteSentReachesTheSelectedChipOnce) {
  this->OnTheBus([](BusDriver& bus) {
    TestFixture::Select(bus, 1);
    TestFixture::Send(bus, 0xA5);
  });

  EXPECT_EQ(this->chips_[1].received, std::vector<std::uint8_t>{0xA5});
}

TYPED_TEST_P(SpiControllerContract, TheSelectedChipsAnswerIsReceived) {
  this->chips_[1].answer = 0x3C;
  std::optional<std::uint8_t> received;

  this->OnTheBus([&](BusDriver& bus) {
    TestFixture::Select(bus, 1);
    received = TestFixture::Send(bus, 0xA5);
  });

  EXPECT_EQ(received, 0x3C);
}

TYPED_TEST_P(SpiControllerContract, AChipThatIsNotSelectedHearsNothing) {
  this->OnTheBus([](BusDriver& bus) {
    TestFixture::Select(bus, 1);
    TestFixture::Send(bus, 0xA5);
  });

  EXPECT_TRUE(this->chips_[0].received.empty());
}

// 🎓 Nothing drives the line back to the controller, and it floats high.
TYPED_TEST_P(SpiControllerContract, AByteSentWhereNoChipIsComesBackAsFf) {
  std::optional<std::uint8_t> received;

  this->OnTheBus([&](BusDriver& bus) {
    TestFixture::Select(bus, 2);
    received = TestFixture::Send(bus, 0xA5);
  });

  EXPECT_EQ(received, 0xFF);
}

TYPED_TEST_P(SpiControllerContract,
             BytesSentWhileAChipIsHeldReachItAsOneFrameThatEndsWhenItIsLetGo) {
  this->OnTheBus([](BusDriver& bus) {
    TestFixture::Select(bus, 1);
    TestFixture::Send(bus, 0x11);
    TestFixture::Send(bus, 0x22);
    TestFixture::LetGo(bus);
  });

  EXPECT_EQ(this->chips_[1].frames,
            (std::vector<std::vector<std::uint8_t>>{{0x11, 0x22}}));
}

REGISTER_TYPED_TEST_SUITE_P(
    SpiControllerContract, AByteSentReachesTheSelectedChipOnce,
    TheSelectedChipsAnswerIsReceived, AChipThatIsNotSelectedHearsNothing,
    AByteSentWhereNoChipIsComesBackAsFf,
    BytesSentWhileAChipIsHeldReachItAsOneFrameThatEndsWhenItIsLetGo);

#endif  // TESTS_CPP_CONTRACTS_SPI_CONTROLLER_CONTRACT_H_
