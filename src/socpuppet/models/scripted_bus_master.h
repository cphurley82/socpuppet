#ifndef SOCPUPPET_MODELS_SCRIPTED_BUS_MASTER_H_
#define SOCPUPPET_MODELS_SCRIPTED_BUS_MASTER_H_

#include <array>
#include <cstdint>
#include <format>
#include <functional>
#include <optional>
#include <span>
#include <stdexcept>
#include <utility>
#include <variant>
#include <vector>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/tlm_quantumkeeper.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/script.h"
#include "socpuppet/platform/errors.h"
#include "socpuppet/platform/failure.h"
#include "socpuppet/platform/time_conversion.h"
#include "socpuppet/platform/transport.h"

namespace socpuppet {

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
  // Where a CPU has its timer interrupt. A script has no use for one, and
  // takes no notice of it. The input is here so that the stand-in fits
  // wherever a CPU does.
  sc_core::sc_in<bool> timer_irq{"timer_irq"};
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
    if (timer_irq.size() == 0) timer_irq.bind(tied_low_);
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
    std::array<std::uint8_t, 4> bytes{};
    if (!Transport(tlm::TLM_READ_COMMAND, op.address, bytes)) {
      return Outcome::kFailed;
    }
    script.GiveBack(LoadLittleEndian<std::uint32_t>(bytes));
    return AfterAnOp();
  }

  Outcome CarryOut(const Write32& op, Script&) {
    std::array bytes = LittleEndianBytes(op.value);
    if (!Transport(tlm::TLM_WRITE_COMMAND, op.address, bytes)) {
      return Outcome::kFailed;
    }
    return AfterAnOp();
  }

  Outcome CarryOut(const Read& op, Script& script) {
    std::vector<std::uint8_t> bytes(op.length);
    if (!Transport(tlm::TLM_READ_COMMAND, op.address, bytes)) {
      return Outcome::kFailed;
    }
    script.GiveBack(std::move(bytes));
    return AfterAnOp();
  }

  Outcome CarryOut(const Write& op, Script&) {
    if (!Transport(tlm::TLM_WRITE_COMMAND, op.address, WriteData(op.data))) {
      return Outcome::kFailed;
    }
    return AfterAnOp();
  }

  Outcome CarryOut(const Expect32& op, Script&) {
    std::array<std::uint8_t, 4> bytes{};
    if (!Transport(tlm::TLM_READ_COMMAND, op.address, bytes)) {
      return Outcome::kFailed;
    }
    const auto actual = LoadLittleEndian<std::uint32_t>(bytes);
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

  // Returns false, having stopped the simulation, if the target refused
  // the access. A script does not get to read zeros from nowhere. The
  // clock is kept and the access allowed to take effect first, so that
  // what the platform shows afterwards is as of the refused access.
  bool Transport(tlm::tlm_command command, std::uint64_t address,
                 std::span<std::uint8_t> data) {
    // The access is stamped with how far ahead of the simulation's clock we
    // are, and the target adds however long the access takes.
    sc_core::sc_time delay = lead_.get_local_time();
    const tlm::tlm_response_status status =
        socpuppet::Transport(socket, command, address, data, delay);
    lead_.set(delay);
    if (lead_.need_sync()) CatchUp();
    LetTheAccessTakeEffect();
    if (status == tlm::TLM_OK_RESPONSE) return true;
    FailSimulation(BusError(std::format(
        "{}: a {} of {} bytes at address {:#x} was refused by the bus ({}). "
        "Check that something is mapped there, and that it takes an access "
        "of that size.",
        name(), command == tlm::TLM_READ_COMMAND ? "read" : "write",
        data.size(), address, ResponseString(status))));
    return false;
  }

  // The access may have changed a line: a handler quiets a device by
  // writing to it. A line takes its new level a delta cycle after it is
  // written, and that is when whatever listens to it (an interrupt
  // controller) runs; what the listener writes in turn takes one more.
  // Without this, a script that quiets its device and then
  // completes the interrupt at a PLIC does so while the PLIC still sees the
  // device asking, and is interrupted again. Two delta cycles is the count
  // that does not depend on the order the kernel runs processes in, and it
  // is what the CPU does after each of its accesses.
  void LetTheAccessTakeEffect() {
    for (int delta = 0;
         delta < 2 && sc_core::sc_pending_activity_at_current_time(); ++delta) {
      wait(sc_core::SC_ZERO_TIME);
    }
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
