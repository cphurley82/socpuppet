#include "socpuppet/models/spi_flash.h"

#include <cstdint>
#include <memory>

#include <generic/spi_mem.h>
#include <minres/gen/apb3spi_regs.h>
#include <minres/qspi.h>
#include <spi/spi_tlm.h>
#include <systemc>
#include <tlm>

#include "socpuppet/models/borrowed_model.h"

namespace socpuppet {

// The borrowed controller and chip, and what they need around them. The
// controller has an interrupt nobody here reads, and a reset that is never
// asserted. The chip is the one device on the controller's SPI bus.
struct SpiFlash::Model {
  Model() {
    controller_.rst_i.bind(reset_tied_low_);
    controller_.irq_o.bind(interrupt_unread_);
    controller_.spi_i(spi_bus_.tsck);
    spi_bus_.isck[0](chip_.spi_t);
  }

 private:
  sc_core::sc_signal<bool> reset_tied_low_{"reset_tied_low"};
  sc_core::sc_signal<bool> interrupt_unread_{"interrupt_unread"};
  PoweredOn<vpvper::minres::qspi> controller_{"controller"};
  spi::spi_channel spi_bus_{"spi_bus", /*slave_count=*/1};
  vpvper::generic::spi_mem chip_{"chip"};

 public:
  BorrowedSocket registers{controller_.socket, "to_registers"};
  // The controller's window onto the chip: it hands an access straight to
  // the chip's memory, with no SPI command in between.
  BorrowedSocket window{controller_.xip_sck, "to_window"};
};

SpiFlash::SpiFlash(const sc_core::sc_module_name& name, std::uint64_t size)
    : sc_module(name), size_(size), model_(std::make_unique<Model>()) {
  socket.register_b_transport(this, &SpiFlash::RegisterAccess);
  xip.register_b_transport(this, &SpiFlash::WindowAccess);
  xip.register_transport_dbg(this, &SpiFlash::DebugWindowAccess);
}

SpiFlash::~SpiFlash() = default;

void SpiFlash::RegisterAccess(tlm::tlm_generic_payload& transaction,
                              sc_core::sc_time& delay) {
  model_->registers.Access(transaction, delay);
}

bool SpiFlash::Fits(const tlm::tlm_generic_payload& transaction) const {
  const std::uint64_t address = transaction.get_address();
  const std::uint64_t length = transaction.get_data_length();
  return address <= size_ && length <= size_ - address;
}

void SpiFlash::WindowAccess(tlm::tlm_generic_payload& transaction,
                            sc_core::sc_time& delay) {
  // The borrowed window would take a write, as a memory does, and the
  // borrowed chip ends the process at an access past its own size.
  if (!transaction.is_read()) {
    transaction.set_response_status(tlm::TLM_COMMAND_ERROR_RESPONSE);
    return;
  }
  if (!Fits(transaction)) {
    transaction.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);
    return;
  }
  model_->window.Access(transaction, delay);
  // The chip's memory says direct access is worth asking for, and the
  // borrowed window then has no way to grant it. Nor should it be had: a
  // boot ROM's reads are to be transactions that a trace can show.
  transaction.set_dmi_allowed(false);
}

unsigned SpiFlash::DebugWindowAccess(tlm::tlm_generic_payload& transaction) {
  if (!Fits(transaction)) return 0;
  return model_->window.DebugAccess(transaction);
}

}  // namespace socpuppet
