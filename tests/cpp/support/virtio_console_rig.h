#ifndef TESTS_CPP_SUPPORT_VIRTIO_CONSOLE_RIG_H_
#define TESTS_CPP_SUPPORT_VIRTIO_CONSOLE_RIG_H_

#include <cstdint>
#include <vector>

#include "socpuppet/core/virtio_console_logic.h"
#include "socpuppet/models/virtio_console.h"
#include "tests/cpp/support/virtqueue_driver.h"

// The console under the virtio device contract: it answers whatever it is
// handed to put out, on its transmit queue, at once; a buffer on its
// receive queue it keeps until something comes in.
struct VirtioConsoleRig {
  using Device = socpuppet::VirtioConsole;
  static constexpr std::uint16_t kAnswersOn =
      socpuppet::VirtioConsoleLogic::kTransmitQueue;
  static void AChainItAnswers(VirtqueueDriver& driver) {
    driver.Describe(0, 4, VirtqueueDriver::kReadable);
    driver.Fill(0, std::vector<std::uint8_t>{'s', 'p', 'a', 'm'});
    driver.MakeAvailable(0);
  }
};

#endif  // TESTS_CPP_SUPPORT_VIRTIO_CONSOLE_RIG_H_
