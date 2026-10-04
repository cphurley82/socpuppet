#include "socpuppet/models/pass_through_link.h"
#include "tests/cpp/contracts/link_contract.h"

INSTANTIATE_TYPED_TEST_SUITE_P(
    PassThrough, LinkContract,
    ::testing::Types<socpuppet::PassThroughLinkEndpoint>);
