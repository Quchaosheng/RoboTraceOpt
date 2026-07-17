#include "service_runtime_demo/context_contract.hpp"

#include <ai_robot_runtime_interfaces/msg/runtime_event.hpp>
#include <ai_robot_runtime_interfaces/msg/trace_header.hpp>
#include <ai_robot_runtime_interfaces/runtime_event_identity.hpp>
#include <ai_robot_runtime_interfaces/srv/runtime_query.hpp>
#include <rclcpp/rclcpp.hpp>

#include <chrono>
#include <cstdint>
#include <iomanip>
#include <memory>
#include <random>
#include <sstream>
#include <string>

namespace service_runtime_demo
{

class ServiceClientNode final : public rclcpp::Node
{
public:
  using RuntimeEvent = ai_robot_runtime_interfaces::msg::RuntimeEvent;
  using RuntimeQuery = ai_robot_runtime_interfaces::srv::RuntimeQuery;
  using TraceHeader = ai_robot_runtime_interfaces::msg::TraceHeader;

  ServiceClientNode()
  : Node("service_runtime_client")
  {
    request_rate_hz_ = this->declare_parameter<double>("request_rate_hz", 2.0);
    server_delay_ms_ = this->declare_parameter<int64_t>("server_delay_ms", 0);
    runtime_events_enabled_ = this->declare_parameter<bool>("runtime_events_enabled", true);
    const auto fault_every_n = this->declare_parameter<int64_t>("fault_every_n", 0);
    fault_every_n_ = fault_every_n > 0 ? static_cast<uint64_t>(fault_every_n) : 0U;

    if (request_rate_hz_ <= 0.0) {
      request_rate_hz_ = 2.0;
    }
    if (server_delay_ms_ < 0) {
      server_delay_ms_ = 0;
    }

    event_publisher_ = this->create_publisher<RuntimeEvent>("/runtime/events", rclcpp::QoS(100));
    client_ = this->create_client<RuntimeQuery>("/runtime/query");
    const auto period = std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::duration<double>(1.0 / request_rate_hz_));
    timer_ = this->create_wall_timer(period, [this]() { send_request(); });
  }

private:
  static int64_t steady_now_ns()
  {
    const auto now = std::chrono::steady_clock::now().time_since_epoch();
    return std::chrono::duration_cast<std::chrono::nanoseconds>(now).count();
  }

  std::string make_oracle_id()
  {
    std::ostringstream stream;
    stream << "oracle_" << std::hex << std::setfill('0')
           << std::setw(16) << oracle_rng_()
           << std::setw(16) << oracle_rng_();
    return stream.str();
  }

  void send_request()
  {
    if (!client_->service_is_ready()) {
      return;
    }

    const uint64_t business_sequence = ++sequence_;
    const uint64_t trace_sequence = context_sequence(business_sequence, fault_every_n_);
    const int64_t timestamp_ns = steady_now_ns();
    const bool faulted = trace_sequence != business_sequence;
    const std::string payload_id = make_payload_id("service_client", business_sequence);

    TraceHeader header;
    header.trace_id = make_trace_id("service_client", timestamp_ns, trace_sequence);
    header.oracle_id = make_oracle_id();
    header.sequence_id = trace_sequence;
    header.source_node = this->get_name();
    header.stage = "query_sent";
    header.timestamp_ns = timestamp_ns;

    auto request = std::make_shared<RuntimeQuery::Request>();
    request->header = header;
    request->payload_id = payload_id;
    request->requested_delay_ms = server_delay_ms_;
    publish_event(header, "query_sent", payload_id, faulted);

    client_->async_send_request(
      request,
      [this, faulted](rclcpp::Client<RuntimeQuery>::SharedFuture future) {
        const auto response = future.get();
        publish_event(response->header, "response_received", response->payload_id, faulted);
      });
  }

  void publish_event(
    const TraceHeader & source_header,
    const std::string & stage,
    const std::string & payload_id,
    const bool faulted)
  {
    if (!runtime_events_enabled_) {
      return;
    }
    RuntimeEvent event;
    event.header = source_header;
    event.header.source_node = this->get_name();
    event.header.stage = stage;
    event.header.timestamp_ns = steady_now_ns();
    event.event_name = stage;
    event.event_type = "service_client";
    ai_robot_runtime_interfaces::populate_runtime_identity(event, "monotonic");
    event.extra_json =
      "{\"payload_id\":\"" + payload_id + "\",\"context_fault_injected\":" +
      (faulted ? "true" : "false") + "}";
    event_publisher_->publish(event);
  }

  rclcpp::Client<RuntimeQuery>::SharedPtr client_;
  rclcpp::Publisher<RuntimeEvent>::SharedPtr event_publisher_;
  rclcpp::TimerBase::SharedPtr timer_;
  double request_rate_hz_{2.0};
  int64_t server_delay_ms_{0};
  bool runtime_events_enabled_{true};
  uint64_t fault_every_n_{0};
  uint64_t sequence_{0};
  std::mt19937_64 oracle_rng_{0x5e7a11ceU};
};

}  // namespace service_runtime_demo

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<service_runtime_demo::ServiceClientNode>());
  rclcpp::shutdown();
  return 0;
}
