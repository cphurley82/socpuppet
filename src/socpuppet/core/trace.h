#pragma once

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

#include "socpuppet/core/time.h"

namespace socpuppet {

// One transaction seen crossing a traced connection.
struct TraceRecord {
  Picoseconds time;    // when it completed
  std::string source;  // the port it came from, such as "compute.cpu.socket"
  std::string sink;    // the port it went to
  bool is_write;
  std::uint64_t address;
  std::vector<std::uint8_t>
      data;  // what was written, or what the read returned
  bool ok;   // false if the target answered with an error

  bool operator==(const TraceRecord&) const = default;
};

// The record of everything seen on traced connections, in the order the
// transactions completed.
class Trace {
 public:
  void record(TraceRecord record) { records_.push_back(std::move(record)); }
  const std::vector<TraceRecord>& records() const { return records_; }

 private:
  std::vector<TraceRecord> records_;
};

}  // namespace socpuppet
