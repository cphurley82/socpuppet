#ifndef SOCPUPPET_MODELS_TIE_LOW_H_
#define SOCPUPPET_MODELS_TIE_LOW_H_

#include <ranges>

#include <systemc>

namespace socpuppet {

// Binds a wire input that nobody connected to `low`, a signal of the
// component's own that nothing ever writes, so that the component sees the
// line low. SystemC insists that every port be bound to something.
//
// Call it from before_end_of_elaboration(), which is SystemC's last chance
// to bind a port and the first moment it is known whether the platform did.
inline void TieLowIfUnconnected(sc_core::sc_in<bool>& input,
                                sc_core::sc_signal<bool>& low) {
  if (input.size() == 0) input.bind(low);
}

// The same for each of several inputs.
template <std::ranges::range Inputs>
void TieLowIfUnconnected(Inputs& inputs, sc_core::sc_signal<bool>& low) {
  for (sc_core::sc_in<bool>& input : inputs) TieLowIfUnconnected(input, low);
}

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_TIE_LOW_H_
