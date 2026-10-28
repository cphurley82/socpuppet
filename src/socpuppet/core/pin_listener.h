#ifndef SOCPUPPET_CORE_PIN_LISTENER_H_
#define SOCPUPPET_CORE_PIN_LISTENER_H_

#include <functional>
#include <optional>

namespace socpuppet {

// Whoever is told what a GPIO's pin now drives: the pin, and its level,
// high, low, or nothing (std::nullopt) when the pin is not an output.
using PinListener = std::function<void(unsigned pin, std::optional<bool>)>;

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_PIN_LISTENER_H_
