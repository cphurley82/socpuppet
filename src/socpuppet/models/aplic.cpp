#include "socpuppet/models/aplic.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>

#include <rvi/aplic.h>
#include <rvi/gen/aplic_regs.h>
#include <scc/utilities.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/models/borrowed_model.h"
#include "socpuppet/models/tie_low.h"

namespace socpuppet {

namespace {

// The register that says how the domain delivers, and the bit in it for
// "by message" (the specification's DM).
constexpr std::uint64_t kDomainConfiguration = 0;
constexpr std::uint8_t kDeliversByMessage = 1U << 2;
constexpr std::size_t kRegisterSize = 4;

// Whether `address` is in a register of a source this APLIC does not
// have. Each source has a register for its mode and one for its target,
// in two rows that have room for 1,023 sources.
constexpr bool IsOfASourceBeyondTheLast(std::uint64_t address) {
  constexpr std::uint64_t kModes = 0x0004;
  constexpr std::uint64_t kModesEnd = 0x1000;
  constexpr std::uint64_t kTargets = 0x3004;
  constexpr std::uint64_t kTargetsEnd = 0x4000;
  constexpr std::uint64_t kOurs = kRegisterSize * Aplic::kSources;
  return (address >= kModes + kOurs && address < kModesEnd) ||
         (address >= kTargets + kOurs && address < kTargetsEnd);
}

// Answers an access to a part of the register map that is reserved: it
// reads as zero and ignores a write.
void AnswerAsReserved(tlm::tlm_generic_payload& transaction) {
  if (transaction.is_read()) {
    std::fill_n(transaction.get_data_ptr(), transaction.get_data_length(),
                static_cast<unsigned char>(0));
  }
  transaction.set_response_status(tlm::TLM_OK_RESPONSE);
}

// The borrowed APLIC as this adapter has it: delivering by message from
// the start. It can also interrupt a hart over a line, and that is what
// its reset leaves it doing.
struct ByMessage : PoweredOn<vpvper::rvi::aplic> {
  using PoweredOn::PoweredOn;

  void start_of_simulation() override {
    PoweredOn::start_of_simulation();
    regs->r_domaincfg.deliverymode = 1;
  }
};

}  // namespace

// The borrowed APLIC and what it needs around it. It has an input for
// each of 1,022 sources and one more for "none", and every one has to be
// bound: 31 are ours and the rest are tied low. Its reset is never asserted.
// Its line to a hart, which is how it interrupts when it does not send
// messages, goes nowhere. Its messages leave by a socket of SCC's "loosely
// timed" kind, which binds only to its like, so they are taken here and passed
// on.
struct Aplic::Model {
  explicit Model(Aplic& owner) : owner_(owner) {
    aplic_.rst_i.bind(reset_tied_low_);
    aplic_.core_interrupt_o.bind(line_unread_);
    aplic_.msi_o.bind(messages_);
    messages_.register_b_transport(this, &Model::PassOn);
    // The borrowed model's inputs are numbered as the sources are, with an
    // input 0 that it never looks at.
    for (std::size_t source = 0;
         source < aplic_.external_global_interrupts_i.size(); ++source) {
      if (source >= 1 && source <= kSources) {
        aplic_.external_global_interrupts_i[source].bind(
            owner.sources[source - 1]);
      } else {
        aplic_.external_global_interrupts_i[source].bind(no_such_source_);
      }
    }
  }

 private:
  void PassOn(tlm::tlm_generic_payload& message, sc_core::sc_time& delay) {
    owner_.msi->b_transport(message, delay);
  }

  Aplic& owner_;
  sc_core::sc_signal<bool> reset_tied_low_{"reset_tied_low"};
  sc_core::sc_signal<bool> no_such_source_{"no_such_source"};
  // Written from whichever process is running, as the borrowed PLIC's is
  // (see plic.cpp), so it is told not to check.
  sc_core::sc_signal<bool, sc_core::SC_UNCHECKED_WRITERS> line_unread_{
      "line_unread"};
  ByMessage aplic_{"aplic"};
  tlm_utils::simple_target_socket<Model, scc::LT> messages_{"messages"};

 public:
  RegistersOf registers{aplic_.socket};
};

Aplic::Aplic(const sc_core::sc_module_name& name)
    : sc_module(name), model_(std::make_unique<Model>(*this)) {
  socket.register_b_transport(this, &Aplic::b_transport);
}

Aplic::~Aplic() = default;

void Aplic::before_end_of_elaboration() {
  TieLowIfUnconnected(sources, tied_low_);
}

void Aplic::b_transport(tlm::tlm_generic_payload& transaction,
                        sc_core::sc_time& delay) {
  // The borrowed model has every source the register map has room for,
  // and this APLIC has 31. A source it does not have cannot be given a
  // mode, and so stays inactive, which nothing else can change.
  if (IsOfASourceBeyondTheLast(transaction.get_address())) {
    AnswerAsReserved(transaction);
    return;
  }
  if (transaction.is_write() &&
      transaction.get_address() == kDomainConfiguration &&
      transaction.get_data_length() <= kRegisterSize) {
    WriteTheDomainConfiguration(transaction, delay);
  } else {
    model_->registers.Access(transaction, delay);
  }
  // The register map also has room for a second domain's message address
  // and for a line to each of thousands of harts, and the borrowed model
  // answers an access to what it does not have with an error. Those parts
  // are reserved too. A driver may touch them without asking first, as
  // Zephyr's does when it says where a supervisor's messages go.
  if (transaction.get_response_status() == tlm::TLM_ADDRESS_ERROR_RESPONSE) {
    AnswerAsReserved(transaction);
  }
}

// This APLIC has no line to a hart, so it delivers by message and cannot
// be told otherwise: the bit that says so is one whatever is written. The
// specification allows that of an APLIC with one way to deliver, and
// Zephyr's driver counts on it, since it never sets the bit. The borrowed
// model has both ways, so the bit is set in what it is given. The bit is
// in the register's first byte, which a write of any length that starts
// at the register has.
void Aplic::WriteTheDomainConfiguration(tlm::tlm_generic_payload& transaction,
                                        sc_core::sc_time& delay) {
  std::array<unsigned char, kRegisterSize> by_message{};
  unsigned char* const written = transaction.get_data_ptr();
  std::copy_n(written, transaction.get_data_length(), by_message.begin());
  by_message[0] |= kDeliversByMessage;
  transaction.set_data_ptr(by_message.data());
  model_->registers.Access(transaction, delay);
  transaction.set_data_ptr(written);
}

}  // namespace socpuppet
