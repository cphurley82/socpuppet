#include <gtest/gtest.h>
#include <scc/router.h>
#include <systemc>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

namespace {

struct Initiator : sc_core::sc_module {
  tlm_utils::simple_initiator_socket<Initiator, scc::LT> socket{"socket"};
  explicit Initiator(const sc_core::sc_module_name& name) : sc_module(name) {}
};

struct Target : sc_core::sc_module {
  tlm_utils::simple_target_socket<Target, scc::LT> socket{"socket"};
  explicit Target(const sc_core::sc_module_name& name) : sc_module(name) {
    socket.register_b_transport(this, &Target::b_transport);
  }
  void b_transport(tlm::tlm_generic_payload&, sc_core::sc_time&) {}
};

}  // namespace

TEST(WhenAnSccRouterIsPartOfAKernelTest, ElaborationSucceeds) {
  Initiator initiator{"initiator"};
  scc::router<> router{"router", 1, 1};
  Target target{"target"};
  initiator.socket.bind(router.target[0]);
  router.bind_target(target.socket, 0, 0x1000, 0x100);

  sc_core::sc_start(sc_core::SC_ZERO_TIME);

  EXPECT_EQ(sc_core::sc_get_status(), sc_core::SC_PAUSED);
}
