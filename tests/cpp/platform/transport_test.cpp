#include "socpuppet/platform/transport.h"

#include <gtest/gtest.h>
#include <tlm>

TEST(WhenATransactionIsPassedOnAtAnotherAddress, ItHasThatAddressMeanwhile) {
  tlm::tlm_generic_payload transaction;
  transaction.set_address(0x1000);

  const socpuppet::AtAddress elsewhere{transaction, 0x20};

  EXPECT_EQ(transaction.get_address(), 0x20U);
}

TEST(WhenATransactionIsPassedOnAtAnotherAddress,
     ItHasItsOwnAddressBackAfterwards) {
  tlm::tlm_generic_payload transaction;
  transaction.set_address(0x1000);

  {
    const socpuppet::AtAddress elsewhere{transaction, 0x20};
  }

  EXPECT_EQ(transaction.get_address(), 0x1000U);
}
