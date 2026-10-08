#ifndef SOCPUPPET_CORE_INTERRUPT_REQUESTS_H_
#define SOCPUPPET_CORE_INTERRUPT_REQUESTS_H_

#include <cstddef>

namespace socpuppet {

// What a device asks of the host on its interrupt vectors, when the host
// is told about an interrupt by the rise of a line (or by the message a
// PCIe endpoint sends when the line rises).
//
// A line that just stayed high while more work waited would tell the host
// nothing. So when the host acknowledges, the device stops asking, even if
// more is waiting, and starts again at the next Rearm(): the line falls,
// and rises again a moment later.
//
// A controller's logic implements this with no simulator attached, and
// InterruptLines (models/interrupt_lines.h) turns it into lines.
class InterruptRequests {
 public:
  virtual ~InterruptRequests() = default;

  // Whether the device is asking for the host's attention on a vector.
  virtual bool Interrupting(std::size_t vector) const = 0;

  // Whether an acknowledgement has quieted a request since the last
  // Rearm().
  virtual bool Quieted() const = 0;

  // Lets what was quieted by an acknowledgement ask again. Call it only
  // once the host has had the chance to see the line low: rearming in the
  // same step as the acknowledgement would hide the fall.
  virtual void Rearm() = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_INTERRUPT_REQUESTS_H_
