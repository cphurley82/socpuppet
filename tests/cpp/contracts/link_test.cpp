#include "link_contract.h"
#include "socpuppet/models/pass_through_link.h"

INSTANTIATE_TYPED_TEST_SUITE_P(
    PassThrough, LinkContract,
    ::testing::Types<socpuppet::PassThroughLinkEndpoint>);
