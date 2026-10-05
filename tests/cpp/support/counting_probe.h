#ifndef TESTS_CPP_SUPPORT_COUNTING_PROBE_H_
#define TESTS_CPP_SUPPORT_COUNTING_PROBE_H_

#include <cstdint>
#include <limits>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

// Sits on a bus connection and counts the transactions that cross it.
// Everything else passes straight through, including requests for direct
// memory access (DMI), which is how a master stops needing transactions.
class CountingProbe : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<CountingProbe> target{"target"};
  tlm_utils::simple_initiator_socket<CountingProbe> initiator{"initiator"};

  explicit CountingProbe(const sc_core::sc_module_name& name)
      : sc_module(name) {
    target.register_b_transport(this, &CountingProbe::b_transport);
    target.register_transport_dbg(this, &CountingProbe::transport_dbg);
    target.register_get_direct_mem_ptr(this,
                                       &CountingProbe::get_direct_mem_ptr);
  }

  // How many transactions have crossed so far.
  std::uint64_t Transactions() const { return transactions_; }

  // Takes back any direct access granted through here, as a memory does
  // when what it handed out is no longer valid, and grants no more.
  void WithdrawDirectAccess() {
    direct_access_withdrawn_ = true;
    target->invalidate_direct_mem_ptr(
        0, std::numeric_limits<sc_dt::uint64>::max());
  }

 private:
  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay) {
    ++transactions_;
    initiator->b_transport(transaction, delay);
  }
  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    return initiator->transport_dbg(transaction);
  }
  bool get_direct_mem_ptr(tlm::tlm_generic_payload& transaction,
                          tlm::tlm_dmi& dmi) {
    if (direct_access_withdrawn_) return false;
    return initiator->get_direct_mem_ptr(transaction, dmi);
  }

  std::uint64_t transactions_ = 0;
  bool direct_access_withdrawn_ = false;
};

#endif  // TESTS_CPP_SUPPORT_COUNTING_PROBE_H_
