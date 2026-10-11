// Question 1 of M14's boot spike: can the borrowed flash be filled by a
// debugger's write through the window it is read through?
//
// VPV-Peripherals' SPI controller (`minres/qspi`) has a second socket,
// `xip_sck`, that a flash is read through as if it were memory (execute in
// place). Its flash chip (`generic/spi_mem`) is a 256 MB memory behind an
// SPI socket. SCC's `spi::spi_channel` joins the two. Here the three are
// joined and a test stands where a bus would.

#include <array>
#include <cstdint>
#include <cstring>
#include <iostream>

#include <generic/spi_mem.h>
#include <gtest/gtest.h>
#include <minres/gen/apb3spi_regs.h>
#include <minres/qspi.h>
#include <scc/utilities.h>
#include <spi/spi_tlm.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>

#include "socpuppet/models/borrowed_model.h"

namespace spike {

namespace {

struct FlashRig : sc_core::sc_module {
  explicit FlashRig(const sc_core::sc_module_name& name) : sc_module(name) {
    controller.set_clock_period(sc_core::sc_time(10, sc_core::SC_NS));
    controller.rst_i.bind(reset_tied_low);
    controller.irq_o.bind(interrupt_unread);
    controller.spi_i(channel.tsck);
    channel.isck[0](chip.spi_t);
    xip.bind(controller.xip_sck);
    registers.bind(controller.socket);
  }

  // One access of `bytes` at `address`, with or without simulated time.
  struct Outcome {
    tlm::tlm_response_status status;
    unsigned transferred;
  };

  Outcome Debug(tlm::tlm_command command, std::uint64_t address,
                unsigned char* bytes, unsigned length) {
    tlm::tlm_generic_payload access;
    Fill(access, command, address, bytes, length);
    const unsigned transferred = xip->transport_dbg(access);
    return {access.get_response_status(), transferred};
  }

  template <typename Socket>
  Outcome Timed(Socket& socket, tlm::tlm_command command, std::uint64_t address,
                unsigned char* bytes, unsigned length) {
    tlm::tlm_generic_payload access;
    Fill(access, command, address, bytes, length);
    sc_core::sc_time delay;
    socket->b_transport(access, delay);
    return {access.get_response_status(), length};
  }

  static void Fill(tlm::tlm_generic_payload& access, tlm::tlm_command command,
                   std::uint64_t address, unsigned char* bytes,
                   unsigned length) {
    access.set_command(command);
    access.set_address(address);
    access.set_data_ptr(bytes);
    access.set_data_length(length);
    access.set_streaming_width(length);
    access.set_response_status(tlm::TLM_INCOMPLETE_RESPONSE);
  }

  socpuppet::PoweredOn<vpvper::minres::qspi> controller{"controller"};
  spi::spi_channel channel{"channel", /*slave_count=*/1};
  vpvper::generic::spi_mem chip{"chip"};
  sc_core::sc_signal<bool> reset_tied_low{"reset_tied_low"};
  sc_core::sc_signal<bool> interrupt_unread{"interrupt_unread"};
  tlm_utils::simple_initiator_socket<FlashRig, scc::LT> xip{"xip"};
  tlm_utils::simple_initiator_socket<FlashRig, scc::LT> registers{"registers"};
};

}  // namespace

// One test, because a process gets one simulation. Each finding is
// printed, and the ones the plan rests on are asserted.
TEST(TheBorrowedFlash, IsFilledByADebugWriteAndReadLikeMemory) {
  FlashRig rig{"rig"};
  // Elaboration, which is as far as `Platform.build()` goes.
  sc_core::sc_start(sc_core::SC_ZERO_TIME);

  // 🧵 Python's loader: a debugger's write, with no process running.
  std::array<unsigned char, 8> image{0xde, 0xad, 0xbe, 0xef, 1, 2, 3, 4};
  const auto loaded =
      rig.Debug(tlm::TLM_WRITE_COMMAND, 0x20'0000, image.data(), image.size());
  std::cout << "debug write: " << loaded.transferred << " bytes, status "
            << loaded.status << "\n";
  EXPECT_EQ(loaded.transferred, image.size());

  std::array<unsigned char, 8> debug_read{};
  const auto peeked = rig.Debug(tlm::TLM_READ_COMMAND, 0x20'0000,
                                debug_read.data(), debug_read.size());
  std::cout << "debug read: " << peeked.transferred << " bytes\n";
  EXPECT_EQ(debug_read, image);

  // A boot ROM's read: a transaction with time, from a thread.
  std::array<unsigned char, 8> read_back{};
  std::array<unsigned char, 4> written{0xff, 0xff, 0xff, 0xff};
  std::array<unsigned char, 4> after_the_write{};
  std::array<unsigned char, 4> status{};
  FlashRig::Outcome read{}, write{}, of_status{};
  bool dmi_offered = false;
  sc_core::sc_spawn([&] {
    sc_core::wait(sc_core::sc_time(1, sc_core::SC_NS));
    read = rig.Timed(rig.xip, tlm::TLM_READ_COMMAND, 0x20'0000,
                     read_back.data(), read_back.size());
    write = rig.Timed(rig.xip, tlm::TLM_WRITE_COMMAND, 0x20'0000,
                      written.data(), written.size());
    rig.Timed(rig.xip, tlm::TLM_READ_COMMAND, 0x20'0000, after_the_write.data(),
              after_the_write.size());
    of_status = rig.Timed(rig.registers, tlm::TLM_READ_COMMAND, 0x4,
                          status.data(), status.size());
    // ⚠️ Not tried here any more: a read at 0x1000'0000, which is 256 MB
    // in and so just past the chip's fixed size, ends the process with
    // "pointer being freed was not allocated". An adapter has to turn an
    // access past its own size away before the chip sees it.
    tlm::tlm_generic_payload access;
    FlashRig::Fill(access, tlm::TLM_READ_COMMAND, 0x20'0000, read_back.data(),
                   4);
    tlm::tlm_dmi dmi;
    dmi_offered = rig.xip->get_direct_mem_ptr(access, dmi);
  });
  sc_core::sc_start(sc_core::sc_time(10, sc_core::SC_NS));

  std::cout << "timed read: status " << read.status << "\n";
  EXPECT_EQ(read.status, tlm::TLM_OK_RESPONSE);
  EXPECT_EQ(read_back, image);

  std::cout << "timed write through the window: status " << write.status
            << ", and the bytes "
            << (std::memcmp(after_the_write.data(), written.data(), 4) == 0
                    ? "changed"
                    : "did not change")
            << "\n";
  std::uint32_t status_value = 0;
  std::memcpy(&status_value, status.data(), 4);
  std::cout << "the controller's status register: status " << of_status.status
            << ", value 0x" << std::hex << status_value << std::dec << "\n";
  std::cout << "DMI through the window: "
            << (dmi_offered ? "offered" : "not offered") << "\n";
}

}  // namespace spike
