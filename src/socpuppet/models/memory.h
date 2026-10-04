#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

namespace socpuppet {

// A flat RAM. peek32 reads directly, without a bus transaction, in host byte
// order.
class Memory : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<Memory> socket{"socket"};

  Memory(const sc_core::sc_module_name& name, std::size_t size)
      : sc_module(name), bytes_(size) {
    socket.register_b_transport(this, &Memory::b_transport);
  }

  std::uint32_t peek32(std::uint64_t address) const {
    std::uint32_t value;
    std::memcpy(&value, &bytes_[address], sizeof value);
    return value;
  }

 private:
  void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    std::memcpy(&bytes_[transaction.get_address()], transaction.get_data_ptr(),
                transaction.get_data_length());
    transaction.set_response_status(tlm::TLM_OK_RESPONSE);
  }

  std::vector<std::uint8_t> bytes_;
};

}  // namespace socpuppet
