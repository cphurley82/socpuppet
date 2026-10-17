#ifndef SOCPUPPET_MODELS_VIRTIO_CONSOLE_H_
#define SOCPUPPET_MODELS_VIRTIO_CONSOLE_H_

#include <string>
#include <string_view>

#include "socpuppet/core/virtio_console_logic.h"
#include "socpuppet/models/far_end.h"
#include "socpuppet/models/virtio_mmio.h"

namespace socpuppet {

// 🎭 The virtio console on the bus, and its far end: whoever holds the
// module is the other end of the serial line, as for the UART (FarEnd).
class VirtioConsole : public VirtioMmio<VirtioConsoleLogic>, public FarEnd {
 public:
  using VirtioMmio::VirtioMmio;

  // Everything the driver has put out so far.
  const std::string& Output() const override { return DeviceLogic().Output(); }

  // Bytes that come in, as if typed at the far end. They go into the
  // buffers the driver has handed over a delta cycle later, in a process
  // of the device's own.
  void Write(std::string_view received) override {
    DeviceLogic().Receive(received);
    Nudge();
  }
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_VIRTIO_CONSOLE_H_
