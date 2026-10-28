#include "socpuppet/models/spi_controller.h"

#include <array>
#include <cstdint>
#include <memory>

#include <generic/tlm_extensions.h>
#include <sifive/gen/spi_regs.h>
#include <sifive/spi.h>
#include <systemc>
#include <tlm/scc/signal_target_mixin.h>
#include <tlm>

#include "socpuppet/core/spi_device.h"
#include "socpuppet/models/borrowed_model.h"

namespace socpuppet {

namespace {

// The controller's clock, which its bit time is a multiple of: 50 MHz.
const sc_core::sc_time kClockPeriod{20, sc_core::SC_NS};

// What a byte reads as when no chip answers it: the line back to the
// controller floats high.
constexpr std::uint8_t kNobody = 0xFF;

using Pin = tlm::scc::tlm_signal_bool_opt_in;
using Signal = tlm::scc::tlm_signal_gp<bool>;
using SpiByte = vpvper::generic::tlm_signal_spi_extension;

}  // namespace

// The borrowed controller and the wires of its bus.
//
// 🎓 The controller moves a byte as transactions on its pins: one on a
// chip select whenever it drives the line (when it falls, when it rises,
// and again at each burst while it is held low), one on the clock when it
// goes idle at the start of a burst, and two on the clock for each byte, as it
// leaves its idle level and comes back. The byte rides on both of a byte's
// clock edges, with room for the chip's answer, so the chip is handed the
// byte on the edge that leaves the idle level: the controller keeps that
// edge's answer and ignores the other. The data out line is left alone,
// since the byte is on the clock's transactions.
struct SpiController::Model {
  Model() {
    controller_.clk_i.bind(clock_);
    controller_.rst_i.bind(reset_tied_low_);
    controller_.irq_o.bind(interrupt_);
    controller_.sck_o.bind(clock_line_);
    for (unsigned line = 0; line < chip_selects_.size(); ++line) {
      controller_.scs_o[line].bind(chip_selects_[line]);
      chip_selects_[line].register_nb_transport(
          [this](unsigned chip_select, Signal& signal, tlm::tlm_phase&,
                 sc_core::sc_time&) {
            ChipSelect(chip_select, signal.get_value());
            return tlm::TLM_COMPLETED;
          },
          line);
    }
    clock_line_.register_nb_transport(
        [this](Signal& signal, tlm::tlm_phase&, sc_core::sc_time&) {
          ClockEdge(signal);
          return tlm::TLM_COMPLETED;
        });
  }

  void Attach(unsigned chip_select, SpiDevice& device) {
    devices_.at(chip_select) = &device;
  }

  // What the borrowed model says its interrupt output is.
  const sc_core::sc_signal_in_if<bool>& Interrupt() const { return interrupt_; }

 private:
  // A chip select line has been driven: low selects its chip, high lets it
  // go. The controller drives a held line low again at each burst, which is
  // no edge and changes nothing.
  void ChipSelect(unsigned chip_select, bool high) {
    const bool selected = !high;  // A line is low while its chip is selected.
    if (selected_[chip_select] == selected) return;
    selected_[chip_select] = selected;
    SpiDevice* device = devices_[chip_select];
    if (device == nullptr) return;
    if (selected) {
      device->Select();
    } else {
      device->Deselect();
    }
  }

  void ClockEdge(Signal& signal) {
    auto* byte = signal.get_extension<SpiByte>();
    if (!byte->tx.m2s_data_valid) {
      idle_ = signal.get_value();
      return;
    }
    if (signal.get_value() == idle_) return;
    byte->tx.s2m_data = Transfer(static_cast<std::uint8_t>(byte->tx.m2s_data));
    byte->tx.s2m_data_valid = true;
  }

  // One byte each way with the chip whose line is low.
  std::uint8_t Transfer(std::uint8_t sent) {
    for (unsigned chip_select = 0; chip_select < devices_.size();
         ++chip_select) {
      if (selected_[chip_select] && devices_[chip_select] != nullptr) {
        return devices_[chip_select]->Transfer(sent);
      }
    }
    return kNobody;
  }

  std::array<SpiDevice*, 4> devices_{};
  sc_core::sc_signal<sc_core::sc_time> clock_{"clock", kClockPeriod};
  sc_core::sc_signal<bool> reset_tied_low_{"reset_tied_low"};
  // The borrowed model writes its output from whichever process is running:
  // its own method when a FIFO fills or drains, and the caller's thread
  // when the receive register is read. SystemC lets one process write a
  // signal in a delta cycle, so this signal is told not to check, and the
  // adapter copies it to `irq` from one process of its own, as the PLIC's
  // does (see docs/upstream.md).
  sc_core::sc_signal<bool, sc_core::SC_UNCHECKED_WRITERS> interrupt_{
      "interrupt"};
  Pin clock_line_{"clock_line"};
  std::array<Pin, 4> chip_selects_{Pin{"chip_select_0"}, Pin{"chip_select_1"},
                                   Pin{"chip_select_2"}, Pin{"chip_select_3"}};
  // Which chip select lines are low.
  std::array<bool, 4> selected_{};
  // The clock's level between bytes, which the controller sends at the
  // start of a burst.
  bool idle_ = false;
  PoweredOn<vpvper::sifive::spi> controller_{"controller"};

 public:
  BorrowedSocket registers{controller_.socket};
};

SpiController::SpiController(const sc_core::sc_module_name& name)
    : sc_module(name), model_(std::make_unique<Model>()) {
  socket.register_b_transport(this, &SpiController::b_transport);
  SC_METHOD(DriveTheLine);
  sensitive << model_->Interrupt();
}

void SpiController::DriveTheLine() { irq.write(model_->Interrupt().read()); }

SpiController::~SpiController() = default;

void SpiController::Attach(unsigned chip_select, SpiDevice& device) {
  model_->Attach(chip_select, device);
}

void SpiController::b_transport(tlm::tlm_generic_payload& transaction,
                                sc_core::sc_time& delay) {
  model_->registers.Access(transaction, delay);
}

}  // namespace socpuppet
