// The speed spike's three loops (milestone M26) on QBox: QEMU's RISC-V CPU
// inside SystemC. The same programs as speed_test.cpp, from loops.h, on a
// platform of QBox's CPU and a RAM that grants direct access. Each test
// prints the same line of JSON, with "cpu": "qbox".
//
// Built into spike_speed_tests when socpuppet is built with QBox
// (SOCPUPPET_QBOX_DIR), which links socpuppet to QBox's SystemC. This file
// is compiled on its own (CMakeLists.txt), because it includes QBox's
// headers, and QBox's fmt and scp/report.h are not socpuppet's.
//
// Two configurations: repeatable, which is QEMU as a coroutine on the
// SystemC thread counting instructions for time, and threaded, which is
// QEMU on threads of its own with nothing to keep it in step, and makes no
// promise that two runs agree.

#include <array>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

#include <cciutils.h>
#include <cpu.h>
#include <gtest/gtest.h>
#include <qemu-instance.h>
#include <riscv64.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "spikes/speed/loops.h"
#include "tests/cpp/support/riscv_program.h"

namespace {

constexpr std::uint64_t kRamBase = 0x8000'0000;
constexpr std::uint64_t kRamSize = 0x4'0000;
constexpr std::uint64_t kFirstTable = kRamBase + 0x1000;
constexpr std::uint64_t kSecondTable = kRamBase + 0x2000;
constexpr std::uint64_t kThirdTable = kRamBase + 0x3000;
constexpr std::uint64_t kResultPage = kRamBase + 0x4000;
constexpr std::uint64_t kFirstDataPage = kRamBase + 0x8000;
constexpr std::uint64_t kDataPages = 32;
constexpr std::uint64_t kTopHalf = 0xFFFF'FFC0'0000'0000;
constexpr std::uint64_t kFirstDataAddress = kTopHalf + 0x2000;
constexpr std::uint64_t kCode =
    riscv::kPteRead | riscv::kPteExecute | riscv::kPteAccessed;
constexpr std::uint64_t kData =
    riscv::kPteRead | riscv::kPteWrite | riscv::kPteAccessed | riscv::kPteDirty;
constexpr riscv::Pages kPages{
    .root_table = kFirstTable, .code = kTopHalf, .result = kTopHalf + 0x1000};
constexpr speed::DataPages kDataLayout{.first = kFirstDataAddress,
                                       .pages = kDataPages};

// A RAM that grants direct access to all of itself, and counts the
// transactions that reach it anyway.
class Ram : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<Ram> socket{"socket"};

  explicit Ram(const sc_core::sc_module_name& name)
      : sc_module(name), bytes_(kRamSize) {
    socket.register_b_transport(this, &Ram::b_transport);
    socket.register_get_direct_mem_ptr(this, &Ram::get_direct_mem_ptr);
    socket.register_transport_dbg(this, &Ram::transport_dbg);
  }

  std::uint8_t* At(std::uint64_t address) {
    return bytes_.data() + (address - kRamBase);
  }
  void Put(std::uint64_t address, std::uint64_t value) {
    std::memcpy(At(address), &value, sizeof value);
  }
  std::uint64_t Word(std::uint64_t address) {
    std::uint64_t value = 0;
    std::memcpy(&value, At(address), sizeof value);
    return value;
  }
  std::uint64_t Transactions() const { return transactions_; }

 private:
  unsigned Copy(tlm::tlm_generic_payload& transaction) {
    const std::uint64_t address = transaction.get_address();
    const unsigned length = transaction.get_data_length();
    if (address < kRamBase || address + length > kRamBase + kRamSize) {
      transaction.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);
      return 0;
    }
    if (transaction.is_read()) {
      std::memcpy(transaction.get_data_ptr(), At(address), length);
    } else {
      std::memcpy(At(address), transaction.get_data_ptr(), length);
    }
    transaction.set_response_status(tlm::TLM_OK_RESPONSE);
    return length;
  }
  void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    ++transactions_;
    Copy(transaction);
    transaction.set_dmi_allowed(true);
  }
  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    return Copy(transaction);
  }
  bool get_direct_mem_ptr(tlm::tlm_generic_payload&, tlm::tlm_dmi& dmi) {
    dmi.set_dmi_ptr(bytes_.data());
    dmi.set_start_address(kRamBase);
    dmi.set_end_address(kRamBase + kRamSize - 1);
    dmi.allow_read_write();
    return true;
  }

  std::vector<std::uint8_t> bytes_;
  std::uint64_t transactions_ = 0;
};

// QBox's 64-bit RISC-V CPU and the RAM, with the CPU's parameters set by
// name before it is built, which is how QBox is configured.
struct QboxPlatform : sc_core::sc_module {
  QboxPlatform(const sc_core::sc_module_name& name, bool threaded)
      : sc_module(name),
        configured_(Configure(this->name(), threaded)),
        instance_("instance", &manager_, QemuInstance::Target::RISCV64),
        core_("core", instance_, 0) {
    core_.socket.bind(ram.socket);
    SC_THREAD(KeepTimeMoving);
  }

  static bool Configure(const std::string& path, bool threaded) {
    cci::cci_broker_handle broker = cci::cci_get_broker();
    const auto set = [&](const std::string& parameter,
                         const cci::cci_value& value) {
      broker.set_preset_cci_value(path + "." + parameter, value);
    };
    if (threaded) {
      set("instance.tcg_mode", cci::cci_value(std::string("MULTI")));
      set("instance.sync_policy",
          cci::cci_value(std::string("multithread-unconstrained")));
      set("instance.icount", cci::cci_value(false));
    } else {
      set("instance.tcg_mode", cci::cci_value(std::string("COROUTINE")));
      set("instance.sync_policy", cci::cci_value(std::string("tlm2")));
      set("instance.icount", cci::cci_value(true));
    }
    set("core.resetvec", cci::cci_value(kRamBase));
    // No physical memory protection: with it and no region set up, QEMU
    // refuses supervisor mode every access, as the specification says.
    set("core.pmp", cci::cci_value(false));
    return true;
  }

  // A QBox CPU asleep in `wfi` stops simulated time with it, so that a run
  // for a fixed length of time never returns (M1's QboxCpu).
  void KeepTimeMoving() {
    for (;;) wait(sc_core::sc_time{100, sc_core::SC_US});
  }

  Ram ram{"ram"};
  bool configured_;
  QemuInstanceManager manager_{"manager"};
  QemuInstance instance_;
  cpu_riscv64 core_;
};

std::string Environment(const char* name, const char* otherwise) {
  const char* value = std::getenv(name);  // NOLINT(concurrency-mt-unsafe)
  return value != nullptr ? value : otherwise;
}

void Measure(const std::string& name, bool threaded, const speed::Loop& loop,
             std::uint64_t result_at) {
  QboxPlatform qbox{"qbox", threaded};
  Ram& ram = qbox.ram;
  ram.Put(kFirstTable + (256 * 8),
          riscv::PageTableEntry(kSecondTable, riscv::kPteValid));
  ram.Put(kSecondTable, riscv::PageTableEntry(kThirdTable, riscv::kPteValid));
  const auto map = [&](std::uint64_t virtual_address, std::uint64_t physical,
                       std::uint64_t bits) {
    ram.Put(kThirdTable + (((virtual_address - kTopHalf) / 0x1000) * 8),
            riscv::PageTableEntry(physical, bits | riscv::kPteValid));
  };
  map(kPages.code, kRamBase, kCode);
  map(kPages.result, kResultPage, kData);
  for (std::uint64_t page = 0; page < kDataPages; ++page) {
    map(kFirstDataAddress + (page * 0x1000), kFirstDataPage + (page * 0x1000),
        kData);
  }
  std::memcpy(ram.At(kRamBase), loop.program.data(),
              loop.program.size() * sizeof(riscv::Word));

  const sc_core::sc_time slice{1, sc_core::SC_MS};
  const auto start = std::chrono::steady_clock::now();
  const auto give_up = start + std::chrono::seconds(300);
  while (ram.Word(result_at) == 0 &&
         std::chrono::steady_clock::now() < give_up) {
    sc_core::sc_start(slice);
  }
  const std::chrono::duration<double> elapsed =
      std::chrono::steady_clock::now() - start;
  ASSERT_NE(ram.Word(result_at), 0U) << "the loop did not finish";
  EXPECT_LT(ram.Transactions(), loop.instructions / 100)
      << "the CPU did not run by direct memory access";

  const double seconds = elapsed.count();
  std::ostringstream line;
  line.precision(6);
  line << "[speed] {"
       << R"("host": ")" << Environment("SPEED_HOST", "unknown") << R"(", )"
       << R"("env": ")" << Environment("SPEED_ENV", "unlabelled") << R"(", )"
       << R"("commit": ")" << Environment("SPEED_COMMIT", "unknown") << R"(", )"
       << R"("run": )" << Environment("SPEED_RUN", "0") << ", "
       << R"("cpu": "qbox", "backend": "qemu", )"
       << R"("mode": ")" << (threaded ? "threaded" : "deterministic")
       << R"(", )"
       << R"("compiler": ")" << SPEED_COMPILER << R"(", )"
       << R"("loop": ")" << name << R"(", )"
       << R"("quantum_us": 100, )"
       << R"("instructions": )" << loop.instructions << ", "
       << R"("walks": )" << loop.walks << ", "
       << R"("seconds": )" << seconds << ", "
       << R"("mips": )"
       << (static_cast<double>(loop.instructions) / seconds / 1e6) << ", "
       << R"("transactions": )" << ram.Transactions() << ", "
       << R"("simulated_s": )" << sc_core::sc_time_stamp().to_seconds() << "}";
  std::cout << line.str() << '\n' << std::flush;
}

constexpr riscv::Word kIterations = 1U << 24;
constexpr riscv::Word kRounds = 1U << 17;

}  // namespace

TEST(Qbox, CountedRepeatable) {
  Measure("counted", false, speed::Counted(kIterations),
          kRamBase + riscv::kResultOffset);
}
TEST(Qbox, WalksRepeatable) {
  Measure("walks", false,
          speed::Paging(kPages, kDataLayout, kRounds, /*empty_the_tlb=*/true),
          kResultPage);
}
TEST(Qbox, HitsRepeatable) {
  Measure("hits", false,
          speed::Paging(kPages, kDataLayout, kRounds, /*empty_the_tlb=*/false),
          kResultPage);
}
TEST(Qbox, CountedThreaded) {
  Measure("counted", true, speed::Counted(kIterations),
          kRamBase + riscv::kResultOffset);
}
TEST(Qbox, WalksThreaded) {
  Measure("walks", true,
          speed::Paging(kPages, kDataLayout, kRounds, /*empty_the_tlb=*/true),
          kResultPage);
}
TEST(Qbox, HitsThreaded) {
  Measure("hits", true,
          speed::Paging(kPages, kDataLayout, kRounds, /*empty_the_tlb=*/false),
          kResultPage);
}
