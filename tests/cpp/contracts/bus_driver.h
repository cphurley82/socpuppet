#ifndef TESTS_CPP_CONTRACTS_BUS_DRIVER_H_
#define TESTS_CPP_CONTRACTS_BUS_DRIVER_H_

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

  bool Granted() const { return pointer_ != nullptr; }
  bool ReadWriteAllowed() const { return read_write_allowed_; }
  // How many bytes the grant covers, from the requested address onwards.
  std::uint64_t BytesToEnd() const { return bytes_to_end_; }

  void Read(std::span<std::uint8_t> data) const {
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

  BusDriver(const sc_core::sc_module_name& name,
            std::function<void(BusDriver&)> body)
      : sc_module(name), body_(std::move(body)) {
    SC_THREAD(Run);
  }

  tlm::tlm_response_status Write(std::uint64_t address,
                                 std::span<const std::uint8_t> data) {
    return Transport(tlm::TLM_WRITE_COMMAND, address,
                     const_cast<std::uint8_t*>(data.data()), data.size());
  }

  tlm::tlm_response_status Read(std::uint64_t address,
                                std::span<std::uint8_t> data) {
    return Transport(tlm::TLM_READ_COMMAND, address, data.data(), data.size());
  }

  // A read from a master that is running `lead` ahead of the simulation's
  // clock, as a CPU model does (temporal decoupling).
  tlm::tlm_response_status ReadAhead(std::uint64_t address,
                                     std::span<std::uint8_t> data,
                                     const sc_core::sc_time& lead) {
    return Transport(tlm::TLM_READ_COMMAND, address, data.data(), data.size(),
                     lead);
  }

  void WaitFor(const sc_core::sc_time& duration) { wait(duration); }

  // Debug transport: an access that takes no simulated time and has no side
  // effects, the way a debugger looks at memory.
  void DebugWrite(std::uint64_t address, std::span<const std::uint8_t> data) {
    Debug(tlm::TLM_WRITE_COMMAND, address,
          const_cast<std::uint8_t*>(data.data()), data.size());
  }

  void DebugRead(std::uint64_t address, std::span<std::uint8_t> data) {
    Debug(tlm::TLM_READ_COMMAND, address, data.data(), data.size());
  }

  // Whether the last Read or Write came back with the target's hint that
  // direct memory access (DMI) is worth asking for. A CPU model waits for
  // this hint before it requests DMI.
  bool DirectMemoryWasOffered() const { return direct_memory_was_offered_; }

  // Asks the target for direct memory access (DMI) at `address`.
  DirectMemory RequestDirectMemory(std::uint64_t address) {
    tlm::tlm_generic_payload transaction;
    transaction.set_address(address);
    tlm::tlm_dmi dmi;
    if (!socket->get_direct_mem_ptr(transaction, dmi)) return DirectMemory{};
    return DirectMemory{dmi, address};
  }

 private:
  void Run() { body_(*this); }

  void Debug(tlm::tlm_command command, std::uint64_t address,
             std::uint8_t* data, std::size_t length) {
    tlm::tlm_generic_payload transaction;
    Fill(transaction, command, address, data, length);
    socket->transport_dbg(transaction);
  }

  tlm::tlm_response_status Transport(
      tlm::tlm_command command, std::uint64_t address, std::uint8_t* data,
      std::size_t length, sc_core::sc_time delay = sc_core::SC_ZERO_TIME) {
    tlm::tlm_generic_payload transaction;
    Fill(transaction, command, address, data, length);
    socket->b_transport(transaction, delay);
    direct_memory_was_offered_ = transaction.is_dmi_allowed();
    return transaction.get_response_status();
  }

  static void Fill(tlm::tlm_generic_payload& transaction,
                   tlm::tlm_command command, std::uint64_t address,
                   std::uint8_t* data, std::size_t length) {
    transaction.set_command(command);
    transaction.set_address(address);
    transaction.set_data_ptr(data);
    transaction.set_data_length(static_cast<unsigned>(length));
    transaction.set_streaming_width(static_cast<unsigned>(length));
  }

  std::function<void(BusDriver&)> body_;
  bool direct_memory_was_offered_ = false;
};

// Looks straight into a target (anything with a TLM target socket called
// `socket`) by debug transport, without a bus in between. For tests that
// need to see or set what a memory holds.
template <typename Target>
void DebugAccess(Target& target, tlm::tlm_command command,
                 std::uint64_t address, std::uint8_t* data,
                 std::size_t length) {
  tlm::tlm_generic_payload transaction;
  transaction.set_command(command);
  transaction.set_address(address);
  transaction.set_data_ptr(data);
  transaction.set_data_length(static_cast<unsigned>(length));
  transaction.set_streaming_width(static_cast<unsigned>(length));
  target.socket.get_base_interface().transport_dbg(transaction);
}

template <typename Target>
void DebugRead(Target& target, std::uint64_t address,
               std::span<std::uint8_t> data) {
  DebugAccess(target, tlm::TLM_READ_COMMAND, address, data.data(), data.size());
}

template <typename Target>
void DebugWrite(Target& target, std::uint64_t address,
                std::span<const std::uint8_t> data) {
  DebugAccess(target, tlm::TLM_WRITE_COMMAND, address,
              const_cast<std::uint8_t*>(data.data()), data.size());
}

#endif  // TESTS_CPP_CONTRACTS_BUS_DRIVER_H_
