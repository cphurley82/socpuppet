#ifndef SPIKES_ISS_QBOX_HARNESS_PROBES_H_
#define SPIKES_ISS_QBOX_HARNESS_PROBES_H_

#include <cstdint>
#include <utility>
#include <vector>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

namespace spike {

// Sits in front of a target and counts the transactions that reach it.
//
// Unlike socpuppet's tracer it keeps no record of them, and it can let
// direct memory access (DMI) through, so the count shows how much traffic
// DMI took off the bus. Built with `allow_dmi` false it refuses DMI and
// withholds the hint, which is how a test turns DMI off.
class CountingProbe : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<CountingProbe> target{"target"};
  tlm_utils::simple_initiator_socket<CountingProbe> initiator{"initiator"};

  CountingProbe(const sc_core::sc_module_name& name, bool allow_dmi)
      : sc_module(name), allow_dmi_(allow_dmi) {
    target.register_b_transport(this, &CountingProbe::b_transport);
    target.register_get_direct_mem_ptr(this,
                                       &CountingProbe::get_direct_mem_ptr);
    target.register_transport_dbg(this, &CountingProbe::transport_dbg);
    initiator.register_invalidate_direct_mem_ptr(
        this, &CountingProbe::invalidate_direct_mem_ptr);
  }

  std::uint64_t Transactions() const { return transactions_; }
  std::uint64_t DmiGrants() const { return dmi_grants_; }

 private:
  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay) {
    ++transactions_;
    initiator->b_transport(transaction, delay);
    if (!allow_dmi_) transaction.set_dmi_allowed(false);
  }

  bool get_direct_mem_ptr(tlm::tlm_generic_payload& transaction,
                          tlm::tlm_dmi& dmi) {
    if (!allow_dmi_) return false;
    const bool granted = initiator->get_direct_mem_ptr(transaction, dmi);
    if (granted) ++dmi_grants_;
    return granted;
  }

  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    return initiator->transport_dbg(transaction);
  }

  void invalidate_direct_mem_ptr(sc_dt::uint64 start, sc_dt::uint64 end) {
    target->invalidate_direct_mem_ptr(start, end);
  }

  bool allow_dmi_;
  std::uint64_t transactions_ = 0;
  std::uint64_t dmi_grants_ = 0;
};

// Drives one wire: it starts at a level and flips at each of the times
// given.
class LineDriver : public sc_core::sc_module {
 public:
  sc_core::sc_out<bool> line{"line"};

  LineDriver(const sc_core::sc_module_name& name, bool initial)
      : sc_module(name), level_(initial) {
    SC_THREAD(Run);
  }

  // Times, counted from the start of the simulation and in increasing
  // order, at which the line flips. Call before the simulation starts.
  void FlipAt(std::vector<sc_core::sc_time> times) {
    flips_ = std::move(times);
  }

 private:
  void Run() {
    line.write(level_);
    for (const sc_core::sc_time& when : flips_) {
      wait(when - sc_core::sc_time_stamp());
      level_ = !level_;
      line.write(level_);
    }
  }

  bool level_;
  std::vector<sc_core::sc_time> flips_;
};

}  // namespace spike

#endif  // SPIKES_ISS_QBOX_HARNESS_PROBES_H_
