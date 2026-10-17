#ifndef SOCPUPPET_MODELS_VIRTIO_CONSOLE_H_
#define SOCPUPPET_MODELS_VIRTIO_CONSOLE_H_

#include <string>
#include <string_view>

#include "socpuppet/core/virtio_console_logic.h"
#include "socpuppet/models/virtio_mmio.h"

namespace socpuppet {

// 🎭 The virtio console on the bus, and its far end: whoever holds the
// module is the other end of the serial line, reading what the driver
// put out with Output() and typing with Write(), as for the UART.
class VirtioConsole : public VirtioMmio<VirtioConsoleLogic> {
 public:
  using VirtioMmio::VirtioMmio;

  // Everything the driver has put out so far.
  const std::string& Output() const { return device().Output(); }

  // Bytes that come in, as if typed at the far end. They go into the
  // buffers the driver has handed over a delta cycle later, in a process
  // of the device's own, since whoever calls this may be a script
  // between two runs.
  void Write(std::string_view received) {
    device().Receive(received);
    Nudge();
  }
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_VIRTIO_CONSOLE_H_
