#pragma once

#include <cstdint>
#include <format>
#include <functional>
#include <stdexcept>
#include <utility>
#include <variant>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>

#include "socpuppet/core/script.h"
#include "socpuppet/platform/failure.h"

namespace socpuppet {

// A script expected one value and read another.
class ExpectationFailed : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

// Stand-in for a CPU: a bus master that carries out a script of operations
// instead of running firmware.
//
// Like a CPU it has an interrupt input and a reset input. While reset is
// high it does nothing, and when reset is released it starts its script
// from the top. An input left unconnected is tied low, as an unused input
// pin would be on a board.
class ScriptedBusMaster : public sc_core::sc_module {
 public:
  tlm_utils::simple_initiator_socket<ScriptedBusMaster> socket{"socket"};
  sc_core::sc_in<bool> irq{"irq"};
  sc_core::sc_in<bool> reset{"reset"};

  explicit ScriptedBusMaster(const sc_core::sc_module_name& name) : sc_module(name) {
    SC_THREAD(run);
  }

  // The script to play, as a function that starts it. It is a function and
  // not a Script because a reset starts the script again from the top. Call
  // before the simulation starts.
  void set_script(std::function<Script()> start_script) {
    start_script_ = std::move(start_script);
  }

  void before_end_of_elaboration() override {
    if (irq.size() == 0) irq.bind(tied_low_);
    if (reset.size() == 0) reset.bind(tied_low_);
  }

 private:
  enum class Outcome { carry_on, interrupted_by_reset, failed };

  void run() {
    if (!start_script_) return;
    // Let one delta cycle pass first, so that a reset line driven high from
    // time zero has taken its value before we look at it.
    wait(sc_core::SC_ZERO_TIME);
    for (;;) {
      while (reset->read()) wait(reset->negedge_event());
      Script script = start_script_();
      Outcome outcome = Outcome::carry_on;
      while (outcome == Outcome::carry_on) {
        const Op* op = script.next();
        if (op == nullptr) break;
        outcome = std::visit([&](const auto& each) { return carry_out(each, script); }, *op);
      }
      if (outcome == Outcome::failed) return;
      if (outcome == Outcome::carry_on) {
        // The script ran to its end. Only a reset starts it again.
        wait(reset->posedge_event());
      }
    }
  }

  Outcome carry_out(const Read32& op, Script& script) {
    script.give_back(read(op.address));
    return after_an_op();
  }

  Outcome carry_out(const Write32& op, Script&) {
    std::uint32_t value = op.value;
    transport(tlm::TLM_WRITE_COMMAND, op.address, value);
    return after_an_op();
  }

  Outcome carry_out(const Expect32& op, Script&) {
    const std::uint32_t actual = read(op.address);
    if (actual != op.value) {
      fail_simulation(ExpectationFailed(
          std::format("{} expected {:#x} at address {:#x}, but read {:#x}.", name(), op.value,
                      op.address, actual)));
      return Outcome::failed;
    }
    return after_an_op();
  }

  Outcome carry_out(const Wait& op, Script&) {
    const sc_core::sc_time duration(static_cast<double>(op.duration.count()), sc_core::SC_PS);
    wait(duration, reset->posedge_event());
    return after_an_op();
  }

  Outcome carry_out(const WaitIrq&, Script&) {
    while (!irq->read() && !reset->read()) {
      wait(irq->posedge_event() | reset->posedge_event());
    }
    return after_an_op();
  }

  Outcome after_an_op() {
    return reset->read() ? Outcome::interrupted_by_reset : Outcome::carry_on;
  }

  std::uint32_t read(std::uint64_t address) {
    std::uint32_t value = 0;
    transport(tlm::TLM_READ_COMMAND, address, value);
    return value;
  }

  void transport(tlm::tlm_command command, std::uint64_t address, std::uint32_t& value) {
    tlm::tlm_generic_payload transaction;
    transaction.set_command(command);
    transaction.set_address(address);
    transaction.set_data_ptr(reinterpret_cast<unsigned char*>(&value));
    transaction.set_data_length(sizeof value);
    transaction.set_streaming_width(sizeof value);
    sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
    socket->b_transport(transaction, delay);
  }

  sc_core::sc_signal<bool> tied_low_{"tied_low"};
  std::function<Script()> start_script_;
};

}  // namespace socpuppet
