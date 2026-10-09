#ifndef TESTS_CPP_SUPPORT_BUS_DRIVER_H_
#define TESTS_CPP_SUPPORT_BUS_DRIVER_H_

#include <algorithm>
#include <array>
#include <cstdint>
#include <functional>
#include <span>
#include <utility>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/platform/transport.h"

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
                     socpuppet::WriteData(data));
  }

  tlm::tlm_response_status Read(std::uint64_t address,
                                std::span<std::uint8_t> data) {
    return Transport(tlm::TLM_READ_COMMAND, address, data);
  }

  // A register's worth at an address: 32 or 64 bits, least significant
  // byte first. A read that nothing answers gives zero. A 64-bit read may
  // be made `lead` ahead of the simulation's clock, as ReadAhead is.
  std::uint32_t Read32(std::uint64_t address) {
    std::array<std::uint8_t, 4> bytes{};
    Read(address, bytes);
    return socpuppet::LoadLittleEndian<std::uint32_t>(bytes);
  }
  tlm::tlm_response_status Write32(std::uint64_t address, std::uint32_t value) {
    return Write(address, socpuppet::LittleEndianBytes(value));
  }
  std::uint64_t Read64(std::uint64_t address,
                       const sc_core::sc_time& lead = sc_core::SC_ZERO_TIME) {
    std::array<std::uint8_t, 8> bytes{};
    ReadAhead(address, bytes, lead);
    return socpuppet::LoadLittleEndian<std::uint64_t>(bytes);
  }
  tlm::tlm_response_status Write64(std::uint64_t address, std::uint64_t value) {
    return Write(address, socpuppet::LittleEndianBytes(value));
  }

  // A read from a master that is running `lead` ahead of the simulation's
  // clock, as a CPU model does (temporal decoupling).
  tlm::tlm_response_status ReadAhead(std::uint64_t address,
                                     std::span<std::uint8_t> data,
                                     const sc_core::sc_time& lead) {
    return Transport(tlm::TLM_READ_COMMAND, address, data, lead);
  }

  void WaitFor(const sc_core::sc_time& duration) { wait(duration); }

  // Debug transport: an access that takes no simulated time and has no side
  // effects, the way a debugger looks at memory. Each returns how many
  // bytes the target transferred, which is none if it declined.
  unsigned DebugWrite(std::uint64_t address,
                      std::span<const std::uint8_t> data) {
    return socpuppet::DebugTransport(socket, tlm::TLM_WRITE_COMMAND, address,
                                     socpuppet::WriteData(data));
  }

  unsigned DebugRead(std::uint64_t address, std::span<std::uint8_t> data) {
    return socpuppet::DebugTransport(socket, tlm::TLM_READ_COMMAND, address,
                                     data);
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

  // Not socpuppet::Transport, because a test wants the DMI hint as well as
  // the response.
  tlm::tlm_response_status Transport(
      tlm::tlm_command command, std::uint64_t address,
      std::span<std::uint8_t> data,
      sc_core::sc_time delay = sc_core::SC_ZERO_TIME) {
    tlm::tlm_generic_payload transaction;
    socpuppet::SetUpAccess(transaction, command, address, data);
    socket->b_transport(transaction, delay);
    direct_memory_was_offered_ = transaction.is_dmi_allowed();
    return transaction.get_response_status();
  }

  std::function<void(BusDriver&)> body_;
  bool direct_memory_was_offered_ = false;
};

// Looks straight into a target (anything with a TLM target socket called
// `socket`) by debug transport, without a bus in between. For tests that
// need to see or set what a memory holds.
template <typename Target>
void DebugAccess(Target& target, tlm::tlm_command command,
                 std::uint64_t address, std::span<std::uint8_t> data) {
  tlm::tlm_generic_payload transaction;
  socpuppet::SetUpAccess(transaction, command, address, data);
  target.socket.get_base_interface().transport_dbg(transaction);
}

template <typename Target>
void DebugRead(Target& target, std::uint64_t address,
               std::span<std::uint8_t> data) {
  DebugAccess(target, tlm::TLM_READ_COMMAND, address, data);
}

template <typename Target>
void DebugWrite(Target& target, std::uint64_t address,
                std::span<const std::uint8_t> data) {
  DebugAccess(target, tlm::TLM_WRITE_COMMAND, address,
              socpuppet::WriteData(data));
}

#endif  // TESTS_CPP_SUPPORT_BUS_DRIVER_H_
