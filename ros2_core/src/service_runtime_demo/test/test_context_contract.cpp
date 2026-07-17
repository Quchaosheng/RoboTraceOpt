#include <gtest/gtest.h>

#include "service_runtime_demo/context_contract.hpp"

TEST(ContextContract, BuildsIndependentBusinessIdentity)
{
  EXPECT_EQ(service_runtime_demo::make_payload_id("service_client", 7), "service_client:7");
}

TEST(ContextContract, InjectsDeterministicSourceContextFault)
{
  EXPECT_EQ(service_runtime_demo::context_sequence(7, 0), 7U);
  EXPECT_EQ(service_runtime_demo::context_sequence(10, 5), 100010U);
  EXPECT_FALSE(service_runtime_demo::is_faulted_sequence(9, 5));
  EXPECT_TRUE(service_runtime_demo::is_faulted_sequence(10, 5));
}
