#ifndef SPIKES_ISS_QBOX_HARNESS_BOOT_H_
#define SPIKES_ISS_QBOX_HARNESS_BOOT_H_

#include <cstddef>
#include <fstream>
#include <functional>
#include <span>
#include <stdexcept>
#include <string>
#include <vector>

#include <systemc>
#include <tlm>

#include "socpuppet/platform/platform.h"
#include "spikes/iss/qbox/harness/rv_asm.h"
#include "spikes/iss/qbox/harness/virt_board.h"

namespace spike {

inline sc_core::sc_time Milliseconds(double count) {
  return {count, sc_core::SC_MS};
}

// Sets the global quantum: how far a CPU model may run ahead of the
// kernel's clock before it has to let the rest of the platform catch up.
// Left at its default of zero, every instruction would be a hand-over.
inline void SetQuantum(const sc_core::sc_time& quantum) {
  tlm::tlm_global_quantum::instance().set(quantum);
}

// Puts an image at the start of the board's RAM, through the CPU's own
// view of the bus. Call after Elaborate().
inline void Load(socpuppet::Platform& platform, const std::string& board,
                 std::span<const std::byte> image) {
  if (!platform.DebugWrite(board + ".cpu.socket", kRamBase, image)) {
    throw std::runtime_error("Could not load the image into " + board +
                             "'s RAM.");
  }
}

inline void Load(socpuppet::Platform& platform, const std::string& board,
                 const rv::Program& program) {
  Load(platform, board, std::as_bytes(std::span{program}));
}

// Where firmware/build.sh leaves the image called `name`.
inline std::string FirmwarePath(const std::string& name) {
  return std::string(SPIKE_FIRMWARE_DIR) + "/" + name;
}

inline bool FileExists(const std::string& path) {
  return std::ifstream(path).good();
}

inline std::vector<std::byte> ReadFile(const std::string& path) {
  std::ifstream file(path, std::ios::binary | std::ios::ate);
  if (!file) throw std::runtime_error("Could not open " + path + ".");
  std::vector<std::byte> bytes(static_cast<std::size_t>(file.tellg()));
  file.seekg(0);
  file.read(reinterpret_cast<char*>(bytes.data()),
            static_cast<std::streamsize>(bytes.size()));
  return bytes;
}

// Runs the simulation a slice at a time until `done` says so, or until
// `budget` of simulated time has passed. Returns whether `done` did.
//
// A CPU that is asleep may still keep the kernel busy, so "run until
// nothing is left to do" cannot be relied on to return.
inline bool RunUntil(socpuppet::Platform& platform,
                     const std::function<bool()>& done,
                     const sc_core::sc_time& budget,
                     const sc_core::sc_time& slice = Milliseconds(1)) {
  const sc_core::sc_time deadline = platform.Time() + budget;
  while (!done() && platform.Time() < deadline) platform.Run(slice);
  return done();
}

// Runs until the board's UART output contains `text`.
inline bool RunUntilPrinted(socpuppet::Platform& platform,
                            const std::string& board, const std::string& text,
                            const sc_core::sc_time& budget) {
  return RunUntil(
      platform,
      [&] {
        return UartOutput(platform, board).find(text) != std::string::npos;
      },
      budget);
}

}  // namespace spike

#endif  // SPIKES_ISS_QBOX_HARNESS_BOOT_H_
