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
#include "tests/cpp/support/sifive_spi_driver.h"

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

  // Two chips, at chip selects 0 and 1. Chip selects 2 and 3 have none.
  std::array<RecordingChip, 2> chips_;
  ControllerType controller_{"controller"};
  sc_core::sc_signal<bool> irq_{"irq"};
};

TYPED_TEST_SUITE_P(SpiControllerContract);

TYPED_TEST_P(SpiControllerContract, AByteSentReachesTheSelectedChipOnce) {
  this->OnTheBus([](BusDriver& bus) {
    const SifiveSpiDriver spi{bus};
    spi.Select(1);
    spi.Send(0xA5);
  });

  EXPECT_EQ(this->chips_[1].received, std::vector<std::uint8_t>{0xA5});
}

TYPED_TEST_P(SpiControllerContract, TheSelectedChipsAnswerIsReceived) {
  this->chips_[1].answer = 0x3C;
  std::optional<std::uint8_t> received;

  this->OnTheBus([&](BusDriver& bus) {
    const SifiveSpiDriver spi{bus};
    spi.Select(1);
    received = spi.Send(0xA5);
  });

  EXPECT_EQ(received, 0x3C);
}

TYPED_TEST_P(SpiControllerContract, AChipThatIsNotSelectedHearsNothing) {
  this->OnTheBus([](BusDriver& bus) {
    const SifiveSpiDriver spi{bus};
    spi.Select(1);
    spi.Send(0xA5);
  });

  EXPECT_TRUE(this->chips_[0].received.empty());
}

// 🎓 Nothing drives the line back to the controller, and it floats high.
TYPED_TEST_P(SpiControllerContract, AByteSentWhereNoChipIsComesBackAsFf) {
  std::optional<std::uint8_t> received;

  this->OnTheBus([&](BusDriver& bus) {
    const SifiveSpiDriver spi{bus};
    spi.Select(2);
    received = spi.Send(0xA5);
  });

  EXPECT_EQ(received, 0xFF);
}

TYPED_TEST_P(SpiControllerContract,
             BytesSentWhileAChipIsHeldReachItAsOneFrameThatEndsWhenItIsLetGo) {
  this->OnTheBus([](BusDriver& bus) {
    const SifiveSpiDriver spi{bus};
    spi.Select(1);
    spi.Send(0x11);
    spi.Send(0x22);
    spi.LetGo();
  });

  EXPECT_EQ(this->chips_[1].frames,
            (std::vector<std::vector<std::uint8_t>>{{0x11, 0x22}}));
}

// Linux's driver, after bytes it only sends, waits for the transmit
// watermark with a mark of one: for the transmit FIFO to be empty, its
// last byte taken to be sent.
TYPED_TEST_P(
    SpiControllerContract,
    AfterTransmitOnlyBytesTheWatermarkOfOneIsPendingOnceTheFifoIsEmpty) {
  bool pending = false;
  std::vector<std::uint8_t> out_by_then;

  this->OnTheBus([&](BusDriver& bus) {
    const SifiveSpiDriver spi{bus};
    spi.Select(1);
    spi.SetTransmitMark(1);
    spi.Format(/*transmit_only=*/true);
    for (const std::uint8_t byte :
         {std::uint8_t{0x11}, std::uint8_t{0x22}, std::uint8_t{0x33}}) {
      spi.Queue(byte);
    }
    pending = spi.WaitFor(SifiveSpiDriver::kTransmitWatermark);
    out_by_then = this->chips_[1].received;
  });

  EXPECT_TRUE(pending);
  EXPECT_EQ(out_by_then, (std::vector<std::uint8_t>{0x11, 0x22, 0x33}));
}

REGISTER_TYPED_TEST_SUITE_P(
    SpiControllerContract, AByteSentReachesTheSelectedChipOnce,
    TheSelectedChipsAnswerIsReceived, AChipThatIsNotSelectedHearsNothing,
    AByteSentWhereNoChipIsComesBackAsFf,
    BytesSentWhileAChipIsHeldReachItAsOneFrameThatEndsWhenItIsLetGo,
    AfterTransmitOnlyBytesTheWatermarkOfOneIsPendingOnceTheFifoIsEmpty);

#endif  // TESTS_CPP_CONTRACTS_SPI_CONTROLLER_CONTRACT_H_
