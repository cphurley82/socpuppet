#ifndef SOCPUPPET_CORE_D2D_LINK_LOGIC_H_
#define SOCPUPPET_CORE_D2D_LINK_LOGIC_H_

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <iterator>
#include <optional>
#include <span>
#include <utility>
#include <vector>

#include "socpuppet/core/link_channel.h"
#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/time.h"
#include "socpuppet/core/ucie_link_registers.h"
#include "socpuppet/core/ucie_link_state.h"
#include "socpuppet/core/ucie_sideband.h"

namespace socpuppet {

// Everything one end of a die-to-die link does, with no simulator
// attached: where the link is on its way up (UcieLinkState), the registers
// its firmware sees (UcieLinkRegisters), and how long a crossing takes
// (LinkChannel). It is what the SystemC model is built around.
//
// Each end holds the channel for the direction leaving its own die, so a
// transaction is given its time where it sets off and arrives at the other
// end with the time already counted.
//
// Nothing is scheduled outside Advance(): a packet is served and answered
// where it arrives, but what firmware asked for by writing a register
// happens in Advance(), and that is the one thing that says when to come
// back.
class D2dLinkLogic {
 public:
  D2dLinkLogic(Picoseconds latency, std::uint64_t bytes_per_ns,
               Picoseconds training)
      : leaving_(latency, bytes_per_ns), state_(training) {}

  // The registers, as the firmware on this die reaches them.
  bool ReadRegister(std::uint64_t offset, std::span<std::uint8_t> out) const {
    return registers_.ReadRegister(offset, out);
  }
  bool WriteRegister(std::uint64_t offset, std::span<const std::uint8_t> in) {
    return registers_.WriteRegister(offset, in);
  }

  // A packet has arrived from the other die, over the sideband.
  void Receive(const SidebandPacket& packet, Picoseconds now);
  // Lets whatever is due at `now` happen, firmware's last word on the
  // registers included, and says when it next wants to be called.
  std::optional<Picoseconds> Advance(Picoseconds now);
  // The packets to send to the other die, which it then no longer holds.
  std::vector<SidebandPacket> TakeOutgoing() {
    return std::exchange(outgoing_, {});
  }

  // Whether the main data path carries anything. Only a trained link does.
  bool IsActive() const { return state_.State() == LinkTrainingState::kActive; }
  // Whether this die is held in reset, and whether the link is asking for
  // its firmware's attention.
  bool ResetAsserted() const { return registers_.ResetAsserted(); }
  bool Interrupting() const { return registers_.Interrupting(); }

  // When a transaction of `bytes` leaving this die at `departure` arrives
  // at the other one.
  Picoseconds Cross(std::size_t bytes, Picoseconds departure) {
    return leaving_.Cross(bytes, departure);
  }

 private:
  // Carries out a register access the other die asked for, against this
  // die's registers, and answers it.
  void Serve(const SidebandPacket& request);
  void DoWhatFirmwareAsked(Picoseconds now);
  // Takes up what the state machine has just done: what the registers say
  // about it, and the packets it wants sent.
  void CatchUpWithTheState() {
    registers_.LinkIs(state_.State());
    std::ranges::move(state_.TakeOutgoing(), std::back_inserter(outgoing_));
  }

  LinkChannel leaving_;
  UcieLinkState state_;
  UcieLinkRegisters registers_;
  std::vector<SidebandPacket> outgoing_;
};

inline void D2dLinkLogic::Receive(const SidebandPacket& packet,
                                  Picoseconds now) {
  switch (packet.opcode) {
    case SidebandOpcode::kMemoryRead32b:
    case SidebandOpcode::kMemoryWrite32b:
      Serve(packet);
      return;
    case SidebandOpcode::kCompletionWithoutData:
    case SidebandOpcode::kCompletionWith32bData:
      // A completion carries 32 bits, which is one register's worth.
      registers_.MailboxAnswered(StatusIn(packet),
                                 static_cast<std::uint32_t>(packet.data));
      return;
    case SidebandOpcode::kMessageWithoutData:
    case SidebandOpcode::kMessageWith64bData:
      break;
  }
  if (MessageIn(packet) == kErrorMessageFatal) registers_.FatalReported();
  state_.Receive(packet, now);
  CatchUpWithTheState();
}

inline std::optional<Picoseconds> D2dLinkLogic::Advance(Picoseconds now) {
  DoWhatFirmwareAsked(now);
  const std::optional<Picoseconds> next = state_.Advance(now);
  CatchUpWithTheState();
  return next;
}

inline void D2dLinkLogic::DoWhatFirmwareAsked(Picoseconds now) {
  const UcieLinkRegisters::Commands asked = registers_.TakeCommands();
  // A fault first, then whatever firmware asked for afterwards: firmware
  // that injects a fault and asks for a retrain in one go means the
  // retrain to answer the fault, not the other way about.
  if (asked.fault) state_.Fault(now);
  if (asked.start_training) state_.StartTraining(now);
  if (asked.retrain) state_.Retrain(now);
  if (asked.mailbox) {
    outgoing_.push_back(
        RegisterAccessPacket(asked.mailbox->opcode, asked.mailbox->address,
                             SidebandAgent::kD2dAdapter,
                             SidebandAgent::kD2dAdapter, asked.mailbox->data));
  }
}

inline void D2dLinkLogic::Serve(const SidebandPacket& request) {
  const std::uint64_t offset = AddressIn(request);
  std::optional<std::uint32_t> data;
  bool served = false;
  if (request.opcode == SidebandOpcode::kMemoryWrite32b) {
    served = registers_.WriteRegister(
        offset, LittleEndianBytes(static_cast<std::uint32_t>(request.data)));
  } else {
    std::array<std::uint8_t, 4> bytes{};
    served = registers_.ReadRegister(offset, bytes);
    if (served) data = LoadLittleEndian<std::uint32_t>(bytes);
  }
  outgoing_.push_back(CompletionPacket(
      served ? SidebandStatus::kSuccess : SidebandStatus::kUnsupportedRequest,
      data, SidebandAgent::kD2dAdapter, SidebandAgent::kD2dAdapter));
}

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_D2D_LINK_LOGIC_H_
