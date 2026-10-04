#pragma once

#include <cstdint>
#include <string>
#include <utility>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/trace.h"
#include "socpuppet/platform/time_conversion.h"

namespace socpuppet {

// Sits on a connection and records every transaction that crosses it.
//
// It refuses direct memory access (DMI). DMI hands the initiator a pointer
// so that later accesses skip the bus altogether, and an access that skips
// the bus also skips the tracer. Refusing keeps every access visible, at
// the price of speed, which is the right trade for a connection someone
// asked to watch.
//
// Debug accesses pass through unrecorded: they are the observer looking
// in, not the platform's own traffic.
class Tracer : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<Tracer> target{"target"};
  tlm_utils::simple_initiator_socket<Tracer> initiator{"initiator"};

  // `source` and `sink` name the two ports of the connection being traced.
  Tracer(const sc_core::sc_module_name& name, std::string source,
         std::string sink, Trace& trace)
      : sc_module(name),
        source_(std::move(source)),
        sink_(std::move(sink)),
        trace_(trace) {
    target.register_b_transport(this, &Tracer::b_transport);
    target.register_transport_dbg(this, &Tracer::transport_dbg);
    // No get_direct_mem_ptr is registered: the socket then answers every
    // request for direct memory access with "no".
  }

 private:
  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay) {
    // Note the address before passing the transaction on: a router further
    // along rewrites it into an offset within the target.
    const std::uint64_t address = transaction.get_address();
    initiator->b_transport(transaction, delay);
    // `delay` is how far ahead of the kernel's clock the initiator is running
    // (temporal decoupling), so the transaction's own time is the sum.
    const sc_core::sc_time when = sc_core::sc_time_stamp() + delay;
    const unsigned char* data = transaction.get_data_ptr();
    trace_.record({.time = to_picoseconds(when),
                   .source = source_,
                   .sink = sink_,
                   .is_write = transaction.is_write(),
                   .address = address,
                   .data = {data, data + transaction.get_data_length()},
                   .ok = transaction.is_response_ok()});
  }

  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    return initiator->transport_dbg(transaction);
  }

  std::string source_;
  std::string sink_;
  Trace& trace_;
};

}  // namespace socpuppet
