#ifndef SOCPUPPET_MODELS_SCRIPTED_BUS_MASTER_H_
#define SOCPUPPET_MODELS_SCRIPTED_BUS_MASTER_H_

#include <cstdint>
#include <format>
#include <functional>
#include <optional>
#include <stdexcept>
#include <utility>
#include <variant>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/tlm_quantumkeeper.h>

#include "socpuppet/core/script.h"
#include "socpuppet/platform/failure.h"
#include "socpuppet/platform/time_conversion.h"

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

  explicit ScriptedBusMaster(const sc_core::sc_module_name& name)
      : sc_module(name) {
    SC_THREAD(Run);
  }

  // The script to play, as a function that starts it. It is a function and
  // not a Script because a reset starts the script again from the top. Call
  // before the simulation starts.
  void SetScript(std::function<Script()> start_script) {
    start_script_ = std::move(start_script);
  }

  void before_end_of_elaboration() override {
    if (irq.size() == 0) irq.bind(tied_low_);
    if (reset.size() == 0) reset.bind(tied_low_);
  }

 private:
  enum class Outcome { kCarryOn, kInterruptedByReset, kFailed };

  void Run() {
    if (!start_script_) return;
    // Let one delta cycle pass first, so that a reset line driven high from
    // time zero has taken its value before we look at it.
    wait(sc_core::SC_ZERO_TIME);
    for (;;) {
      while (reset->read()) wait(reset->negedge_event());
      lead_.reset();
      script_.emplace(start_script_());
      Outcome outcome = Outcome::kCarryOn;
      while (outcome == Outcome::kCarryOn) {
        const Op* op = script_->Next();
        if (op == nullptr) break;
        outcome = std::visit(
            [&](const auto& each) { return CarryOut(each, *script_); }, *op);
      }
      if (outcome == Outcome::kFailed) return;
      if (outcome == Outcome::kCarryOn) {
        // The script ran to its end. Only a reset starts it again, and one
        // may have come while the clock was catching up.
        CatchUp();
        if (!reset->read()) wait(reset->posedge_event());
      }
    }
  }

  Outcome CarryOut(const Read32& op, Script& script) {
    script.GiveBack(Read(op.address));
    return AfterAnOp();
  }

  Outcome CarryOut(const Write32& op, Script&) {
    std::uint32_t value = op.value;
    Transport(tlm::TLM_WRITE_COMMAND, op.address, value);
    return AfterAnOp();
  }

  Outcome CarryOut(const Expect32& op, Script&) {
    const std::uint32_t actual = Read(op.address);
    if (actual != op.value) {
      FailSimulation(ExpectationFailed(
          std::format("{} expected {:#x} at address {:#x}, but read {:#x}.",
                      name(), op.value, op.address, actual)));
      return Outcome::kFailed;
    }
    return AfterAnOp();
  }

  Outcome CarryOut(const Wait& op, Script&) {
    CatchUp();
    if (!reset->read()) wait(ToScTime(op.duration), reset->posedge_event());
    return AfterAnOp();
  }

  Outcome CarryOut(const WaitIrq&, Script&) {
    CatchUp();
    while (!irq->read() && !reset->read()) {
      wait(irq->posedge_event() | reset->posedge_event());
    }
    return AfterAnOp();
  }

  Outcome AfterAnOp() {
    return reset->read() ? Outcome::kInterruptedByReset : Outcome::kCarryOn;
  }

  std::uint32_t Read(std::uint64_t address) {
    std::uint32_t value = 0;
    Transport(tlm::TLM_READ_COMMAND, address, value);
    return value;
  }

  void Transport(tlm::tlm_command command, std::uint64_t address,
                 std::uint32_t& value) {
    tlm::tlm_generic_payload transaction;
    transaction.set_command(command);
    transaction.set_address(address);
    transaction.set_data_ptr(reinterpret_cast<unsigned char*>(&value));
    transaction.set_data_length(sizeof value);
    transaction.set_streaming_width(sizeof value);
    // The access is stamped with how far ahead of the simulation's clock we
    // are, and the target adds however long the access takes.
    sc_core::sc_time delay = lead_.get_local_time();
    socket->b_transport(transaction, delay);
    lead_.set(delay);
    if (lead_.need_sync()) CatchUp();
  }

  // Lets the simulation's clock catch up with us, unless a reset comes
  // first. Skipped when we are not ahead: with no quantum every access asks
  // for a sync, and a wait of zero would still hand control to everyone
  // else for a delta cycle.
  void CatchUp() {
    if (lead_.get_local_time() == sc_core::SC_ZERO_TIME) return;
    wait(lead_.get_local_time(), reset->posedge_event());
    lead_.reset();
  }

  sc_core::sc_signal<bool> tied_low_{"tied_low"};
  // How far ahead of the simulation's clock the master has run. Time that
  // targets add to its accesses collects here, and the master only stops
  // to let the clock catch up once it is a whole quantum ahead (temporal
  // decoupling), or before it waits for something.
  tlm_utils::tlm_quantumkeeper lead_;
  std::function<Script()> start_script_;
  // The script being played. It is kept here, and not as a local of Run(),
  // because SystemC never unwinds a thread's stack: when a simulation ends
  // part-way through a script, a local would never be destroyed.
  std::optional<Script> script_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_SCRIPTED_BUS_MASTER_H_
