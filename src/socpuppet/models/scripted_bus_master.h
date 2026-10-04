#pragma once

#include <cstdint>
#include <utility>
#include <vector>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>

namespace socpuppet {

struct Write32 {
  std::uint64_t address;
  std::uint32_t value;
};

// A bus master that plays a fixed list of operations, in order.
class ScriptedBusMaster : public sc_core::sc_module {
 public:
  tlm_utils::simple_initiator_socket<ScriptedBusMaster> socket{"socket"};

  ScriptedBusMaster(const sc_core::sc_module_name& name, std::vector<Write32> ops)
      : sc_module(name), ops_(std::move(ops)) {
    SC_THREAD(play);
  }

 private:
  void play() {
    for (Write32& op : ops_) {
      tlm::tlm_generic_payload transaction;
      transaction.set_command(tlm::TLM_WRITE_COMMAND);
      transaction.set_address(op.address);
      transaction.set_data_ptr(reinterpret_cast<unsigned char*>(&op.value));
      transaction.set_data_length(sizeof op.value);
      transaction.set_streaming_width(sizeof op.value);
      sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
      socket->b_transport(transaction, delay);
    }
  }

  std::vector<Write32> ops_;
};

}  // namespace socpuppet
