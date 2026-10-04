#pragma once

#include <algorithm>
#include <cstdint>
#include <functional>
#include <span>
#include <utility>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>

// What a target handed back when asked for direct memory access (DMI): a
// pointer to its bytes that works without a transaction per access.
class DirectMemory {
 public:
  DirectMemory() = default;  // not granted
  DirectMemory(const tlm::tlm_dmi& dmi, std::uint64_t address)
      : pointer_(dmi.get_dmi_ptr() + (address - dmi.get_start_address())),
        bytes_to_end_(dmi.get_end_address() - address + 1),
        read_write_allowed_(dmi.is_read_write_allowed()) {}

  bool granted() const { return pointer_ != nullptr; }
  bool read_write_allowed() const { return read_write_allowed_; }
  // How many bytes the grant covers, from the requested address onwards.
  std::uint64_t bytes_to_end() const { return bytes_to_end_; }

  void read(std::span<std::uint8_t> data) const {
    std::copy_n(pointer_, data.size(), data.begin());
  }

 private:
  const std::uint8_t* pointer_ = nullptr;
  std::uint64_t bytes_to_end_ = 0;
  bool read_write_allowed_ = false;
};

// A test's hands on the bus: runs the given body inside a simulation thread,
// where it can issue transactions through `socket`.
class BusDriver : public sc_core::sc_module {
 public:
  tlm_utils::simple_initiator_socket<BusDriver> socket{"socket"};

  BusDriver(const sc_core::sc_module_name& name, std::function<void(BusDriver&)> body)
      : sc_module(name), body_(std::move(body)) {
    SC_THREAD(run);
  }

  tlm::tlm_response_status write(std::uint64_t address, std::span<const std::uint8_t> data) {
    return transport(tlm::TLM_WRITE_COMMAND, address, const_cast<std::uint8_t*>(data.data()),
                     data.size());
  }

  tlm::tlm_response_status read(std::uint64_t address, std::span<std::uint8_t> data) {
    return transport(tlm::TLM_READ_COMMAND, address, data.data(), data.size());
  }

  // Debug transport: an access that takes no simulated time and has no side
  // effects, the way a debugger looks at memory.
  void debug_write(std::uint64_t address, std::span<const std::uint8_t> data) {
    debug(tlm::TLM_WRITE_COMMAND, address, const_cast<std::uint8_t*>(data.data()), data.size());
  }

  void debug_read(std::uint64_t address, std::span<std::uint8_t> data) {
    debug(tlm::TLM_READ_COMMAND, address, data.data(), data.size());
  }

  // Asks the target for direct memory access (DMI) at `address`.
  DirectMemory direct_memory(std::uint64_t address) {
    tlm::tlm_generic_payload transaction;
    transaction.set_address(address);
    tlm::tlm_dmi dmi;
    if (!socket->get_direct_mem_ptr(transaction, dmi)) return DirectMemory{};
    return DirectMemory{dmi, address};
  }

 private:
  void run() { body_(*this); }

  void debug(tlm::tlm_command command, std::uint64_t address, std::uint8_t* data,
             std::size_t length) {
    tlm::tlm_generic_payload transaction;
    fill(transaction, command, address, data, length);
    socket->transport_dbg(transaction);
  }

  tlm::tlm_response_status transport(tlm::tlm_command command, std::uint64_t address,
                                     std::uint8_t* data, std::size_t length) {
    tlm::tlm_generic_payload transaction;
    fill(transaction, command, address, data, length);
    sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
    socket->b_transport(transaction, delay);
    return transaction.get_response_status();
  }

  static void fill(tlm::tlm_generic_payload& transaction, tlm::tlm_command command,
                   std::uint64_t address, std::uint8_t* data, std::size_t length) {
    transaction.set_command(command);
    transaction.set_address(address);
    transaction.set_data_ptr(data);
    transaction.set_data_length(static_cast<unsigned>(length));
    transaction.set_streaming_width(static_cast<unsigned>(length));
  }

  std::function<void(BusDriver&)> body_;
};
