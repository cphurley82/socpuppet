#ifndef TESTS_CPP_SUPPORT_RECORDING_TARGET_H_
#define TESTS_CPP_SUPPORT_RECORDING_TARGET_H_

#include <cstdint>
#include <vector>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

// One access as a target saw it arrive.
struct RecordedAccess {
  std::uint64_t address;
  // How far ahead of the simulation's clock the master said it was running.
  sc_core::sc_time delay;
  // The simulation's clock when the access arrived.
  sc_core::sc_time kernel_time;
};

// A test's ears on the bus: a target that accepts every access and writes
// down when it came. The record belongs to the test, so it can be read
// after the simulation is over.
class RecordingTarget : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<RecordingTarget> socket{"socket"};

  RecordingTarget(const sc_core::sc_module_name& name,
                  std::vector<RecordedAccess>& record)
      : sc_module(name), record_(record) {
    socket.register_b_transport(this, &RecordingTarget::b_transport);
  }

 private:
  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay) {
    record_.push_back({.address = transaction.get_address(),
                       .delay = delay,
                       .kernel_time = sc_core::sc_time_stamp()});
    transaction.set_response_status(tlm::TLM_OK_RESPONSE);
  }

  std::vector<RecordedAccess>& record_;
};

#endif  // TESTS_CPP_SUPPORT_RECORDING_TARGET_H_
