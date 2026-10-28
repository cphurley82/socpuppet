#ifndef TESTS_CPP_CONTRACTS_SPI_CONTROLLER_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_SPI_CONTROLLER_CONTRACT_H_

#include <array>
#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/core/spi_device.h"
#include "socpuppet/platform/slots.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/line_watcher.h"
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
    void Select() override {
      NoteTheCaller();
      frame_.emplace();
    }
    std::uint8_t Transfer(std::uint8_t sent) override {
      NoteTheCaller();
      received.push_back(sent);
      if (frame_) frame_->push_back(sent);
      return answer;
    }
    void Deselect() override {
      NoteTheCaller();
      if (frame_) frames.push_back(*frame_);
      frame_.reset();
    }

    std::uint8_t answer = 0;
    std::vector<std::uint8_t> received;
    // Every frame that has ended.
    std::vector<std::vector<std::uint8_t>> frames;
    // The process each call came from.
    struct Caller {
      std::string name;
      sc_core::sc_curr_proc_kind kind;
    };
    std::vector<Caller> callers;

   private:
    void NoteTheCaller() {
      const sc_core::sc_process_handle process =
          sc_core::sc_get_current_process_handle();
      callers.push_back({.name = process.name(), .kind = process.proc_kind()});
    }

    std::optional<std::vector<std::uint8_t>> frame_;
  };

  SpiControllerContract() {
    controller_.irq.bind(irq_);
    interrupt_.line.bind(irq_);
    for (unsigned chip_select = 0; chip_select < chips_.size(); ++chip_select) {
      controller_.Attach(chip_select, chips_[chip_select]);
    }
  }

  // Runs `body` in a simulation thread wired to the controller. The run
  // ends a delta cycle after the body does: the controller tells a chip it
  // is let go a delta cycle on.
  void OnTheBus(const std::function<void(BusDriver&)>& body) {
    BusDriver driver{"driver", [&](BusDriver& bus) {
                       body(bus);
                       sc_core::wait(sc_core::SC_ZERO_TIME);
                       sc_core::sc_stop();
                     }};
    driver.socket.bind(controller_.socket);
    sc_core::sc_start();
  }

  // Two chips, at chip selects 0 and 1. Chip selects 2 and 3 have none.
  std::array<RecordingChip, 2> chips_;
  // Any clock will do: what the contract asks of a controller takes no
  // time it counts.
  ControllerType controller_{"controller", 50'000'000};
  sc_core::sc_signal<bool> irq_{"irq"};
  LineWatcher interrupt_{"interrupt"};
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

// Linux's driver queues a transfer's bytes and then reads the watermark, at
// once: what it reads must be about the bytes it has just queued, and not
// the last transfer's empty FIFO.
TYPED_TEST_P(SpiControllerContract,
             APendingWatermarkOfOneIsNoLongerPendingAsSoonAsAByteIsQueued) {
  bool pending_before_queueing = false;
  bool pending_after_queueing = true;

  this->OnTheBus([&](BusDriver& bus) {
    const SifiveSpiDriver spi{bus};
    spi.Select(1);
    spi.SetTransmitMark(1);
    spi.Format(/*transmit_only=*/true);
    spi.Queue(0x11);
    pending_before_queueing = spi.WaitFor(SifiveSpiDriver::kTransmitWatermark);
    spi.Queue(0x22);
    pending_after_queueing = spi.Pending(SifiveSpiDriver::kTransmitWatermark);
  });

  ASSERT_TRUE(pending_before_queueing);
  EXPECT_FALSE(pending_after_queueing);
}

// Linux's driver sends a command's opcode and address transmit-only, then
// reads the data that follows: what it reads must be the data's answer,
// not one kept from the bytes before.
TYPED_TEST_P(SpiControllerContract,
             AnswersToBytesSentTransmitOnlyAreNotKeptForTheNextTransfer) {
  bool sent = false;
  std::optional<std::uint8_t> received;

  this->OnTheBus([&](BusDriver& bus) {
    const SifiveSpiDriver spi{bus};
    spi.Select(1);
    spi.SetTransmitMark(1);
    this->chips_[1].answer = 0xAA;
    spi.Format(/*transmit_only=*/true);
    spi.Queue(0x11);
    sent = spi.WaitFor(SifiveSpiDriver::kTransmitWatermark);
    this->chips_[1].answer = 0xBB;
    spi.Format(/*transmit_only=*/false);
    received = spi.Send(0x22);
  });

  ASSERT_TRUE(sent);
  EXPECT_EQ(received, 0xBB);
}

// Linux's driver, for a transfer that reads, queues its bytes, sets the
// receive watermark's mark one below their count, waits for it, and then
// takes every answer: they must all be there by then.
TYPED_TEST_P(SpiControllerContract,
             AReceiveWatermarkOfTwoIsPendingOnceThreeAnswersAreIn) {
  bool pending = false;
  std::vector<std::optional<std::uint8_t>> taken;

  this->OnTheBus([&](BusDriver& bus) {
    const SifiveSpiDriver spi{bus};
    spi.Select(1);
    spi.Format(/*transmit_only=*/false);
    for (const std::uint8_t byte :
         {std::uint8_t{0x11}, std::uint8_t{0x22}, std::uint8_t{0x33}}) {
      spi.Queue(byte);
    }
    spi.SetReceiveMark(2);
    pending = spi.WaitFor(SifiveSpiDriver::kReceiveWatermark);
    for (int answer = 0; answer < 3; ++answer) taken.push_back(spi.Take());
  });

  EXPECT_TRUE(pending);
  EXPECT_THAT(taken, ::testing::Each(::testing::Optional(::testing::_)));
}

// Linux's driver, at a slow enough clock, sleeps on the interrupt: it
// enables the watermark it waits for, and its handler disables it again.
TYPED_TEST_P(
    SpiControllerContract,
    TheInterruptIsUpWhileAnEnabledWatermarkIsPendingAndDownOnceDisabled) {
  bool up = false;
  bool down = false;

  this->OnTheBus([&](BusDriver& bus) {
    const SifiveSpiDriver spi{bus};
    spi.Select(1);
    spi.SetTransmitMark(1);
    spi.Format(/*transmit_only=*/true);
    spi.Queue(0x11);
    spi.Enable(SifiveSpiDriver::kTransmitWatermark);
    up = this->interrupt_.WaitForLevel(true, SifiveSpiDriver::Patience());
    spi.Enable(0);
    down = this->interrupt_.WaitForLevel(false, SifiveSpiDriver::Patience());
  });

  EXPECT_TRUE(up);
  EXPECT_TRUE(down);
}

// A chip may wait in any call, as one that is a Python object does to
// reach Python: so it is called from the controller's own processes, never
// from the thread of whoever wrote its registers, which may be a CPU's that
// must not wait.
TYPED_TEST_P(SpiControllerContract,
             AChipIsCalledOnlyFromTheControllersOwnProcesses) {
  this->OnTheBus([](BusDriver& bus) {
    const SifiveSpiDriver spi{bus};
    spi.Select(1);
    spi.Send(0xA5);
    spi.LetGo();
  });

  using Caller = typename TestFixture::RecordingChip::Caller;
  const std::string controller = std::string(this->controller_.name()) + ".";
  EXPECT_THAT(
      this->chips_[1].callers,
      ::testing::AllOf(
          ::testing::Not(::testing::IsEmpty()),
          ::testing::Each(::testing::AllOf(
              ::testing::Field(&Caller::name,
                               ::testing::StartsWith(controller)),
              // A method process cannot wait.
              ::testing::Field(&Caller::kind,
                               ::testing::Ne(sc_core::SC_METHOD_PROC_))))));
}

// A driver that lets a chip go and selects it again at once, as a CPU
// running ahead of the clock does, starts a second frame: the chip is told
// it was let go before it is selected again.
TYPED_TEST_P(SpiControllerContract,
             AChipLetGoAndSelectedAgainAtOnceSeesTwoFramesInOrder) {
  this->OnTheBus([](BusDriver& bus) {
    const SifiveSpiDriver spi{bus};
    spi.Select(1);
    spi.Send(0x11);
    spi.LetGo();
    spi.Select(1);
    spi.Send(0x22);
    spi.LetGo();
  });

  EXPECT_EQ(this->chips_[1].frames,
            (std::vector<std::vector<std::uint8_t>>{{0x11}, {0x22}}));
}

// A CPU running ahead of the clock may read the receive FIFO long after the
// answers came: a byte whose answer has no room waits to be sent, and no
// answer is lost.
TYPED_TEST_P(SpiControllerContract,
             NoAnswerIsLostWhenTheReceiveFifoIsFullAsBytesComeToBeSent) {
  int answers = 0;

  this->OnTheBus([&](BusDriver& bus) {
    const SifiveSpiDriver spi{bus};
    spi.Select(1);
    // Eight bytes, which fill the receive FIFO with their answers once
    // they are out; then two more, with no room for theirs.
    for (int byte = 0; byte < 8; ++byte) spi.Queue(0);
    bus.WaitFor(SifiveSpiDriver::Patience());
    for (int byte = 0; byte < 2; ++byte) spi.Queue(0);
    bus.WaitFor(SifiveSpiDriver::Patience());
    while (spi.Take()) {
      ++answers;
      // The bytes that waited for room go now, and their answers come.
      bus.WaitFor(SifiveSpiDriver::Patience());
    }
  });

  EXPECT_EQ(answers, 10);
}

REGISTER_TYPED_TEST_SUITE_P(
    SpiControllerContract, AByteSentReachesTheSelectedChipOnce,
    TheSelectedChipsAnswerIsReceived, AChipThatIsNotSelectedHearsNothing,
    AByteSentWhereNoChipIsComesBackAsFf,
    BytesSentWhileAChipIsHeldReachItAsOneFrameThatEndsWhenItIsLetGo,
    AfterTransmitOnlyBytesTheWatermarkOfOneIsPendingOnceTheFifoIsEmpty,
    APendingWatermarkOfOneIsNoLongerPendingAsSoonAsAByteIsQueued,
    AnswersToBytesSentTransmitOnlyAreNotKeptForTheNextTransfer,
    AReceiveWatermarkOfTwoIsPendingOnceThreeAnswersAreIn,
    TheInterruptIsUpWhileAnEnabledWatermarkIsPendingAndDownOnceDisabled,
    AChipIsCalledOnlyFromTheControllersOwnProcesses,
    AChipLetGoAndSelectedAgainAtOnceSeesTwoFramesInOrder,
    NoAnswerIsLostWhenTheReceiveFifoIsFullAsBytesComeToBeSent);

#endif  // TESTS_CPP_CONTRACTS_SPI_CONTROLLER_CONTRACT_H_
