#ifndef SOCPUPPET_MODELS_FAR_END_H_
#define SOCPUPPET_MODELS_FAR_END_H_

#include <string>
#include <string_view>

namespace socpuppet {

// The far end of a serial line: whoever holds the module reads what the
// firmware has put out and types what it is to receive. 🎓 The UART and
// the virtio console are two transports with this one far end, which is
// why a script sits at either the same way.
class FarEnd {
 public:
  virtual ~FarEnd() = default;

  // Everything transmitted so far.
  virtual const std::string& Output() const = 0;

  // Bytes that come in, as if typed at the other end. They show in the
  // transport a delta cycle later, in a process of its own, since whoever
  // calls this may be a script between two runs.
  virtual void Write(std::string_view received) = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_FAR_END_H_
