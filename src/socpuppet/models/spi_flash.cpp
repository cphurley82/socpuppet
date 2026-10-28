#include "socpuppet/models/spi_flash.h"

#include <algorithm>
#include <cstdint>
#include <span>

#include <systemc>
#include <tlm>

namespace socpuppet {

SpiFlash::SpiFlash(const sc_core::sc_module_name& name, std::uint64_t size)
    : sc_module(name), chip_(size) {
  controller_.irq.bind(interrupt_unread_);
  controller_.Attach(0, chip_);
  socket.bind(controller_.socket);
  xip.register_b_transport(this, &SpiFlash::WindowAccess);
  xip.register_transport_dbg(this, &SpiFlash::DebugWindowAccess);
}

bool SpiFlash::Fits(const tlm::tlm_generic_payload& transaction) {
  const std::uint64_t size = chip_.Bytes().size();
  const std::uint64_t address = transaction.get_address();
  const std::uint64_t length = transaction.get_data_length();
  return address <= size && length <= size - address;
}

void SpiFlash::WindowAccess(tlm::tlm_generic_payload& transaction,
                            sc_core::sc_time& /*delay*/) {
  // A flash is written by commands to its controller, not by stores.
  if (!transaction.is_read()) {
    transaction.set_response_status(tlm::TLM_COMMAND_ERROR_RESPONSE);
    return;
  }
  if (!Fits(transaction)) {
    transaction.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);
    return;
  }
  Copy(transaction);
  transaction.set_response_status(tlm::TLM_OK_RESPONSE);
}

unsigned SpiFlash::DebugWindowAccess(tlm::tlm_generic_payload& transaction) {
  if (!Fits(transaction)) return 0;
  Copy(transaction);
  return transaction.get_data_length();
}

void SpiFlash::Copy(tlm::tlm_generic_payload& transaction) {
  const std::span<std::uint8_t> chip = chip_.Bytes().subspan(
      transaction.get_address(), transaction.get_data_length());
  const std::span<std::uint8_t> data{transaction.get_data_ptr(),
                                     transaction.get_data_length()};
  if (transaction.is_read()) {
    std::ranges::copy(chip, data.begin());
  } else {
    std::ranges::copy(data, chip.begin());
  }
}

}  // namespace socpuppet
