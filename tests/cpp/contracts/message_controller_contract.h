#ifndef TESTS_CPP_CONTRACTS_MESSAGE_CONTROLLER_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_MESSAGE_CONTROLLER_CONTRACT_H_

#include <array>
#include <cstdint>
#include <functional>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/models/hart_registers.h"
#include "socpuppet/platform/slots.h"
#include "tests/cpp/support/bus_driver.h"

// A device that interrupts with messages, for the contract below: it
// writes an interrupt identity to a page of the controller's when a test
// asks it to. It does so from a thread of its own, as a device on a
// platform does, and not from the thread of whoever asked.
class MessageSender {
 public:
  // Where on a page a message is written, as 32 bits with the least
  // significant byte first. The AIA specification calls it seteipnum_le.
  static constexpr std::uint64_t kSeteipnumLe = 0x000;

  explicit MessageSender(const char* name)
      : bus{name, [this](BusDriver& page) {
              for (;;) {
                sc_core::wait(asked_);
                page.Write32(kSeteipnumLe, identity_);
              }
            }} {}

  // Has the device send a message for `identity`, a delta cycle on.
  void Send(std::uint32_t identity) {
    identity_ = identity;
    asked_.notify(sc_core::SC_ZERO_TIME);
  }

  // The device's access to the page, for binding and for a test that
  // looks at the page itself.
  BusDriver bus;

 private:
  std::uint32_t identity_ = 0;
  sc_core::sc_event asked_;
};

// What every interrupt controller that is sent messages must do, whatever
// is behind it: a RISC-V IMSIC, with an interrupt file for machine mode
// and one for supervisor mode. This is what an operating system's
// interrupt handling relies on, and what a device that interrupts with a
// message relies on.
//
// To hold an implementation to this contract:
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, MessageControllerContract,
//                                  ::testing::Types<MyImsic>);
// MyImsic must fit the message controller slot (see
// socpuppet/platform/slots.h).
template <socpuppet::MessageControllerSlot ControllerType>
class MessageControllerContract : public ::testing::Test {
 protected:
  // The highest identity the controller is built with.
  static constexpr std::uint32_t kIdentities = 63;

  // The registers of an interrupt file, by the numbers the AIA
  // specification selects them with: whether the file may interrupt at
  // all, and which identities firmware wants to hear of, a bit each.
  static constexpr std::uint32_t kEidelivery = 0x70;
  static constexpr std::uint32_t kEie0 = 0xC0;

  // One of the controller's two interrupt files, as a test gets at it.
  struct File {
    // The hart's register that is the window onto the file's own, and the
    // one that reads the file's top identity and, written, claims it.
    std::uint32_t window;
    std::uint32_t top;
    // Whoever sends the file its messages.
    MessageSender& devices;
    // The file's interrupt line to the hart.
    const sc_core::sc_signal<bool>& line;
  };

  MessageControllerContract() {
    controller_.irq.bind(interrupt_);
    controller_.supervisor_irq.bind(supervisor_interrupt_);
    machines_devices_.bus.socket.bind(controller_.machine);
    supervisors_devices_.bus.socket.bind(controller_.supervisor);
  }

  // Runs `body` in a simulation thread wired to the controller as its
  // hart is, to completion, and then lets what it set in motion settle.
  void AsTheHart(const std::function<void(BusDriver&)>& body) {
    BusDriver driver{"hart", [&](BusDriver& hart) {
                       body(hart);
                       Settle();
                     }};
    driver.socket.bind(controller_.csr);
    sc_core::sc_start();
  }

  // Lets a change, and what follows from it, happen.
  static void Settle() { sc_core::wait(sc_core::sc_time{1, sc_core::SC_NS}); }

  // What firmware does through the hart: reads and writes a register of
  // an interrupt file.
  static std::uint64_t ReadRegister(BusDriver& hart, const File& file,
                                    std::uint32_t reg) {
    return hart.Read64(socpuppet::HartRegisterAddress(file.window, reg));
  }
  static tlm::tlm_response_status WriteRegister(BusDriver& hart,
                                                const File& file,
                                                std::uint32_t reg,
                                                std::uint64_t value) {
    return hart.Write64(socpuppet::HartRegisterAddress(file.window, reg),
                        value);
  }

  // Lets a file interrupt its hart at all, which a file cannot until
  // firmware says so.
  static void SwitchDeliveryOn(BusDriver& hart, const File& file) {
    WriteRegister(hart, file, kEidelivery, 1);
    Settle();
  }

  // Has a file listen for one more identity (below 64).
  static void Enable(BusDriver& hart, const File& file,
                     std::uint32_t identity) {
    WriteRegister(
        hart, file, kEie0,
        ReadRegister(hart, file, kEie0) | (std::uint64_t{1} << identity));
    Settle();
  }

  // What a device does: sends a file a message.
  static void Send(const File& file, std::uint32_t identity) {
    file.devices.Send(identity);
    Settle();
  }

  // What a handler does first: takes the file's top identity, which is
  // then no longer pending. Returns it, or zero if there was none. The
  // register has the identity in bits 26 to 16.
  static std::uint32_t Claim(BusDriver& hart, const File& file) {
    const std::uint64_t address = socpuppet::HartRegisterAddress(file.top);
    const auto top = static_cast<std::uint32_t>(hart.Read64(address) >> 16U);
    hart.Write64(address, 0);
    Settle();
    return top & 0x7FFU;
  }

  ControllerType controller_{"controller", kIdentities};
  MessageSender machines_devices_{"machines_devices"};
  MessageSender supervisors_devices_{"supervisors_devices"};
  // A wire takes one driver, so a controller drives each line from one
  // process of its own, whether a message landed, from a device's thread,
  // or its hart wrote to it, from the hart's.
  sc_core::sc_signal<bool> interrupt_{"interrupt"};
  sc_core::sc_signal<bool> supervisor_interrupt_{"supervisor_interrupt"};

  const File machine_mode_{.window = socpuppet::kMireg,
                           .top = socpuppet::kMtopei,
                           .devices = machines_devices_,
                           .line = interrupt_};
  const File supervisor_mode_{.window = socpuppet::kSireg,
                              .top = socpuppet::kStopei,
                              .devices = supervisors_devices_,
                              .line = supervisor_interrupt_};
};

TYPED_TEST_SUITE_P(MessageControllerContract);

TYPED_TEST_P(MessageControllerContract,
             AMessageForAnIdentityFirmwareEnabledRaisesTheFilesLine) {
  bool interrupted_before = true;

  this->AsTheHart([&](BusDriver& hart) {
    this->SwitchDeliveryOn(hart, this->machine_mode_);
    this->Enable(hart, this->machine_mode_, 5);
    interrupted_before = this->machine_mode_.line.read();
    this->Send(this->machine_mode_, 5);
  });

  EXPECT_FALSE(interrupted_before);
  EXPECT_TRUE(this->machine_mode_.line.read());
}

TYPED_TEST_P(MessageControllerContract,
             AMessageForAnIdentityFirmwareHasNotEnabledWaitsUntilItIs) {
  bool interrupted_before = true;

  this->AsTheHart([&](BusDriver& hart) {
    this->SwitchDeliveryOn(hart, this->machine_mode_);
    this->Send(this->machine_mode_, 5);
    interrupted_before = this->machine_mode_.line.read();
    this->Enable(hart, this->machine_mode_, 5);
  });

  EXPECT_FALSE(interrupted_before);
  EXPECT_TRUE(this->machine_mode_.line.read());
}

TYPED_TEST_P(MessageControllerContract,
             UntilFirmwareSwitchesDeliveryOnNoMessageRaisesTheLine) {
  bool interrupted_before = true;

  this->AsTheHart([&](BusDriver& hart) {
    this->Enable(hart, this->machine_mode_, 5);
    this->Send(this->machine_mode_, 5);
    interrupted_before = this->machine_mode_.line.read();
    this->SwitchDeliveryOn(hart, this->machine_mode_);
  });

  EXPECT_FALSE(interrupted_before);
  EXPECT_TRUE(this->machine_mode_.line.read());
}

// A lower identity has the higher priority.
TYPED_TEST_P(MessageControllerContract,
             AClaimGivesTheLowestIdentityAndTheLineFallsWhenNoneIsLeft) {
  std::uint32_t first = 0;
  bool interrupting_after_the_first = false;
  std::uint32_t second = 0;

  this->AsTheHart([&](BusDriver& hart) {
    this->SwitchDeliveryOn(hart, this->machine_mode_);
    this->Enable(hart, this->machine_mode_, 9);
    this->Enable(hart, this->machine_mode_, 5);
    this->Send(this->machine_mode_, 9);
    this->Send(this->machine_mode_, 5);
    first = this->Claim(hart, this->machine_mode_);
    interrupting_after_the_first = this->machine_mode_.line.read();
    second = this->Claim(hart, this->machine_mode_);
  });

  EXPECT_EQ(first, 5U);
  EXPECT_TRUE(interrupting_after_the_first);
  EXPECT_EQ(second, 9U);
  EXPECT_FALSE(this->machine_mode_.line.read());
}

// What is pending is a bit and not a count. A device that sends twice
// before its handler has run is heard once, as with a line that stays up.
TYPED_TEST_P(MessageControllerContract,
             TwoMessagesForOneIdentityBeforeItIsClaimedAreOne) {
  std::uint32_t first = 0;
  std::uint32_t second = 0;

  this->AsTheHart([&](BusDriver& hart) {
    this->SwitchDeliveryOn(hart, this->machine_mode_);
    this->Enable(hart, this->machine_mode_, 5);
    this->Send(this->machine_mode_, 5);
    this->Send(this->machine_mode_, 5);
    first = this->Claim(hart, this->machine_mode_);
    second = this->Claim(hart, this->machine_mode_);
  });

  EXPECT_EQ(first, 5U);
  EXPECT_EQ(second, 0U);
}

// The register a claim is made through has the identity twice over: in
// bits 26 to 16, and again in the low eleven as its priority, which with
// messages is the same number. One driver reads the first and another the
// second.
TYPED_TEST_P(MessageControllerContract,
             ReadingTheTopIdentityGivesItTwiceOverAndClaimsNothing) {
  std::uint64_t first = 0;
  std::uint64_t second = 0;

  this->AsTheHart([&](BusDriver& hart) {
    this->SwitchDeliveryOn(hart, this->machine_mode_);
    this->Enable(hart, this->machine_mode_, 5);
    this->Send(this->machine_mode_, 5);
    const std::uint64_t top =
        socpuppet::HartRegisterAddress(this->machine_mode_.top);
    first = hart.Read64(top);
    second = hart.Read64(top);
  });

  EXPECT_EQ(first, (std::uint64_t{5} << 16U) | 5U);
  EXPECT_EQ(second, first);
  EXPECT_TRUE(this->machine_mode_.line.read());
}

// Each mode has a file of its own, a page of its own for its messages and
// a line of its own to the hart.
TYPED_TEST_P(MessageControllerContract,
             AMessageToTheSupervisorsPageRaisesTheSupervisorsLineOnly) {
  this->AsTheHart([&](BusDriver& hart) {
    // Both files are listening for the identity, so that a message that
    // went to the wrong one, or to both, would show.
    for (const auto* file : {&this->machine_mode_, &this->supervisor_mode_}) {
      this->SwitchDeliveryOn(hart, *file);
      this->Enable(hart, *file, 5);
    }
    this->Send(this->supervisor_mode_, 5);
  });

  EXPECT_TRUE(this->supervisor_mode_.line.read());
  EXPECT_FALSE(this->machine_mode_.line.read());
}

TYPED_TEST_P(MessageControllerContract,
             TheSupervisorClaimsFromItsOwnFileThroughItsOwnRegister) {
  std::uint32_t claimed_by_the_machine = 0;
  std::uint32_t claimed_by_the_supervisor = 0;

  this->AsTheHart([&](BusDriver& hart) {
    this->SwitchDeliveryOn(hart, this->supervisor_mode_);
    this->Enable(hart, this->supervisor_mode_, 5);
    this->Send(this->supervisor_mode_, 5);
    claimed_by_the_machine = this->Claim(hart, this->machine_mode_);
    claimed_by_the_supervisor = this->Claim(hart, this->supervisor_mode_);
  });

  EXPECT_EQ(claimed_by_the_machine, 0U);
  EXPECT_EQ(claimed_by_the_supervisor, 5U);
  EXPECT_FALSE(this->supervisor_mode_.line.read());
}

// A message is a write. Nothing can be learned of a file from its page.
TYPED_TEST_P(MessageControllerContract, AReadOfAMessagePageGivesZero) {
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  // Not zero to begin with, so that a page that answered with nothing at
  // all would show.
  std::array<std::uint8_t, 4> read{0xFF, 0xFF, 0xFF, 0xFF};

  this->AsTheHart([&](BusDriver& hart) {
    this->Enable(hart, this->machine_mode_, 5);
    this->Send(this->machine_mode_, 5);
    response =
        this->machines_devices_.bus.Read(MessageSender::kSeteipnumLe, read);
  });

  EXPECT_EQ(response, tlm::TLM_OK_RESPONSE);
  EXPECT_EQ(socpuppet::LoadLittleEndian<std::uint32_t>(read), 0U);
}

// The rest of a page is the specification's to use, and reads as zero.
TYPED_TEST_P(MessageControllerContract,
             AWriteElsewhereInAPageIsTakenAndMakesNothingPending) {
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  std::uint32_t claimed = 0xFFFF'FFFF;

  this->AsTheHart([&](BusDriver& hart) {
    this->SwitchDeliveryOn(hart, this->machine_mode_);
    this->Enable(hart, this->machine_mode_, 5);
    response = this->machines_devices_.bus.Write32(0x800, 5);
    this->Settle();
    claimed = this->Claim(hart, this->machine_mode_);
  });

  EXPECT_EQ(response, tlm::TLM_OK_RESPONSE);
  EXPECT_EQ(claimed, 0U);
}

// A message is 32 bits wide.
TYPED_TEST_P(MessageControllerContract,
             AWriteOfAnotherWidthToAPageIsRefusedAndMakesNothingPending) {
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  std::uint32_t claimed = 0xFFFF'FFFF;

  this->AsTheHart([&](BusDriver& hart) {
    this->SwitchDeliveryOn(hart, this->machine_mode_);
    this->Enable(hart, this->machine_mode_, 5);
    response =
        this->machines_devices_.bus.Write64(MessageSender::kSeteipnumLe, 5);
    this->Settle();
    claimed = this->Claim(hart, this->machine_mode_);
  });

  EXPECT_EQ(response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
  EXPECT_EQ(claimed, 0U);
}

// A hart takes an illegal-instruction trap for a register that is not
// there, and an address error is how the controller says so.
TYPED_TEST_P(MessageControllerContract,
             AHartRegisterTheControllerHasNotIsRefused) {
  tlm::tlm_response_status a_write_to_an_odd_numbered_register_of_bits =
      tlm::TLM_INCOMPLETE_RESPONSE;
  tlm::tlm_response_status a_read_of_one = tlm::TLM_INCOMPLETE_RESPONSE;
  tlm::tlm_response_status the_selector = tlm::TLM_INCOMPLETE_RESPONSE;
  tlm::tlm_response_status no_register_of_the_controllers =
      tlm::TLM_INCOMPLETE_RESPONSE;

  this->AsTheHart([&](BusDriver& hart) {
    // With registers of 64 bits the odd-numbered ones do not exist.
    a_write_to_an_odd_numbered_register_of_bits =
        this->WriteRegister(hart, this->machine_mode_, this->kEie0 + 1, 1);
    std::array<std::uint8_t, 8> read{};
    a_read_of_one = hart.Read(
        socpuppet::HartRegisterAddress(socpuppet::kMireg, this->kEie0 + 1),
        read);
    // What selects a window's register is the hart's own to keep.
    the_selector = hart.Write64(
        socpuppet::HartRegisterAddress(socpuppet::kMiselect), this->kEie0);
    // `mstatus`, which is the hart's own.
    no_register_of_the_controllers =
        hart.Write64(socpuppet::HartRegisterAddress(0x300), 0);
  });

  EXPECT_EQ(a_write_to_an_odd_numbered_register_of_bits,
            tlm::TLM_ADDRESS_ERROR_RESPONSE);
  EXPECT_EQ(a_read_of_one, tlm::TLM_ADDRESS_ERROR_RESPONSE);
  EXPECT_EQ(the_selector, tlm::TLM_ADDRESS_ERROR_RESPONSE);
  EXPECT_EQ(no_register_of_the_controllers, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}

// A hart's register is eight bytes, and an access is of all of it.
TYPED_TEST_P(MessageControllerContract,
             AHartAccessThatIsNotOfEightBytesIsRefused) {
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;

  this->AsTheHart([&](BusDriver& hart) {
    response = hart.Write32(
        socpuppet::HartRegisterAddress(socpuppet::kMireg, this->kEidelivery),
        1);
  });

  EXPECT_EQ(response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}

REGISTER_TYPED_TEST_SUITE_P(
    MessageControllerContract,
    AMessageForAnIdentityFirmwareEnabledRaisesTheFilesLine,
    AMessageForAnIdentityFirmwareHasNotEnabledWaitsUntilItIs,
    UntilFirmwareSwitchesDeliveryOnNoMessageRaisesTheLine,
    AClaimGivesTheLowestIdentityAndTheLineFallsWhenNoneIsLeft,
    TwoMessagesForOneIdentityBeforeItIsClaimedAreOne,
    ReadingTheTopIdentityGivesItTwiceOverAndClaimsNothing,
    AMessageToTheSupervisorsPageRaisesTheSupervisorsLineOnly,
    TheSupervisorClaimsFromItsOwnFileThroughItsOwnRegister,
    AReadOfAMessagePageGivesZero,
    AWriteElsewhereInAPageIsTakenAndMakesNothingPending,
    AWriteOfAnotherWidthToAPageIsRefusedAndMakesNothingPending,
    AHartRegisterTheControllerHasNotIsRefused,
    AHartAccessThatIsNotOfEightBytesIsRefused);

#endif  // TESTS_CPP_CONTRACTS_MESSAGE_CONTROLLER_CONTRACT_H_
