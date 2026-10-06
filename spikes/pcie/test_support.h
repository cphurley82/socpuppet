#ifndef SPIKES_PCIE_TEST_SUPPORT_H_
#define SPIKES_PCIE_TEST_SUPPORT_H_

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <deque>
#include <span>
#include <string>
#include <vector>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

namespace spike {

// One transaction, as somebody on the receiving side saw it arrive.
struct Seen {
  tlm::tlm_command command = tlm::TLM_IGNORE_COMMAND;
  std::uint64_t address = 0;
  unsigned length = 0;
  // The first four bytes of a write's data, little-endian.
  std::uint32_t word = 0;
  // The process that sent it: its name, and whether it is an SC_THREAD
  // (which may wait) or an SC_METHOD (which may not).
  std::string process;
  bool from_thread = false;
  // How far ahead of the clock the sender said it was.
  sc_core::sc_time lead;
  // Where its data is, to tell whether the data was copied on the way.
  const unsigned char* data = nullptr;
};

inline Seen Describe(const tlm::tlm_generic_payload& transaction,
                     const sc_core::sc_time& lead) {
  Seen seen{.command = transaction.get_command(),
            .address = transaction.get_address(),
            .length = transaction.get_data_length(),
            .lead = lead,
            .data = transaction.get_data_ptr()};
  if (transaction.is_write()) {
    std::memcpy(&seen.word, transaction.get_data_ptr(),
                std::min<std::size_t>(seen.length, sizeof seen.word));
  }
  const sc_core::sc_process_handle process =
      sc_core::sc_get_current_process_handle();
  seen.process = process.valid() ? process.name() : "(no process)";
  seen.from_thread =
      process.valid() && process.proc_kind() == sc_core::SC_THREAD_PROC_;
  return seen;
}

// Sits in a bus connection and writes down every transaction that crosses
// it. Requests for direct memory access (DMI) cross it too, so that a
// source which then stops sending transactions shows up as silence.
class BusSpy : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<BusSpy> target{"target"};
  tlm_utils::simple_initiator_socket<BusSpy> initiator{"initiator"};
  std::vector<Seen> seen;
  int direct_memory_requests = 0;

  explicit BusSpy(const sc_core::sc_module_name& name) : sc_module(name) {
    target.register_b_transport(this, &BusSpy::b_transport);
    target.register_get_direct_mem_ptr(this, &BusSpy::get_direct_mem_ptr);
    initiator.register_invalidate_direct_mem_ptr(
        this, &BusSpy::invalidate_direct_mem_ptr);
  }

 private:
  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay) {
    seen.push_back(Describe(transaction, delay));
    initiator->b_transport(transaction, delay);
  }
  bool get_direct_mem_ptr(tlm::tlm_generic_payload& transaction,
                          tlm::tlm_dmi& dmi) {
    ++direct_memory_requests;
    return initiator->get_direct_mem_ptr(transaction, dmi);
  }
  void invalidate_direct_mem_ptr(sc_dt::uint64 start, sc_dt::uint64 end) {
    target->invalidate_direct_mem_ptr(start, end);
  }
};

// 🎭 Holds a function's place behind the endpoint: a register block that
// remembers what was written to it, a DMA port, and interrupt lines that
// the test moves by hand.
class FunctionStandIn : public sc_core::sc_module {
 public:
  static constexpr std::size_t kRegistersSize = 0x2000;

  tlm_utils::simple_target_socket<FunctionStandIn> bar0{"bar0"};
  tlm_utils::simple_initiator_socket<FunctionStandIn> dma{"dma"};
  sc_core::sc_vector<sc_core::sc_out<bool>> irq;
  std::vector<Seen> accesses;
  // How long the function says each register access takes.
  sc_core::sc_time access_time = sc_core::SC_ZERO_TIME;

  FunctionStandIn(const sc_core::sc_module_name& name, std::size_t vectors)
      : sc_module(name), irq("irq", vectors) {
    bar0.register_b_transport(this, &FunctionStandIn::b_transport);
  }

  // DMA, from whichever simulation thread calls.
  tlm::tlm_response_status DmaWrite(std::uint64_t address,
                                    std::span<const std::uint8_t> data) {
    return Dma(tlm::TLM_WRITE_COMMAND, address,
               const_cast<std::uint8_t*>(data.data()), data.size());
  }
  tlm::tlm_response_status DmaRead(std::uint64_t address,
                                   std::span<std::uint8_t> data) {
    return Dma(tlm::TLM_READ_COMMAND, address, data.data(), data.size());
  }

 private:
  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay) {
    accesses.push_back(Describe(transaction, delay));
    delay += access_time;
    const std::uint64_t end =
        transaction.get_address() + transaction.get_data_length();
    if (end > registers_.size()) {
      transaction.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);
      return;
    }
    std::uint8_t* at = registers_.data() + transaction.get_address();
    if (transaction.is_read()) {
      std::memcpy(transaction.get_data_ptr(), at,
                  transaction.get_data_length());
    } else {
      std::memcpy(at, transaction.get_data_ptr(),
                  transaction.get_data_length());
    }
    transaction.set_response_status(tlm::TLM_OK_RESPONSE);
  }

  tlm::tlm_response_status Dma(tlm::tlm_command command, std::uint64_t address,
                               std::uint8_t* data, std::size_t length) {
    tlm::tlm_generic_payload transaction;
    transaction.set_command(command);
    transaction.set_address(address);
    transaction.set_data_ptr(data);
    transaction.set_data_length(static_cast<unsigned>(length));
    transaction.set_streaming_width(static_cast<unsigned>(length));
    sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
    dma->b_transport(transaction, delay);
    return transaction.get_response_status();
  }

  std::array<std::uint8_t, kRegistersSize> registers_{};
};

// Where MSI-X messages land: the page of the host's address space that an
// interrupt controller would listen on. It writes down each message, and
// for the message whose data is N it pulses line N, so that something
// waiting for an interrupt line can wait for a message.
class MsiCatcher : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<MsiCatcher> socket{"socket"};
  sc_core::sc_vector<sc_core::sc_out<bool>> line;
  std::vector<Seen> messages;

  MsiCatcher(const sc_core::sc_module_name& name, std::size_t lines)
      : sc_module(name), line("line", lines) {
    socket.register_b_transport(this, &MsiCatcher::b_transport);
    SC_METHOD(Pulse);
    sensitive << pulse_;
    dont_initialize();
  }

 private:
  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay) {
    const Seen message = Describe(transaction, delay);
    transaction.set_response_status(tlm::TLM_OK_RESPONSE);
    if (!transaction.is_write()) return;
    messages.push_back(message);
    if (message.word < line.size()) {
      to_pulse_.push_back(message.word);
      pulse_.notify(sc_core::SC_ZERO_TIME);
    }
  }

  // Lowers whatever is high, and a delta cycle later raises the next one.
  void Pulse() {
    bool lowered = false;
    for (auto& each : line) {
      lowered = lowered || each.read();
      each.write(false);
    }
    if (!lowered && !to_pulse_.empty()) {
      line[to_pulse_.front()].write(true);
      to_pulse_.pop_front();
      lowered = true;  // it has to come down again
    }
    if (lowered) pulse_.notify(sc_core::SC_ZERO_TIME);
  }

  std::deque<std::uint32_t> to_pulse_;
  sc_core::sc_event pulse_;
};

}  // namespace spike

#endif  // SPIKES_PCIE_TEST_SUPPORT_H_
