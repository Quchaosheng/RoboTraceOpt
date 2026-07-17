#include <ai_robot_runtime_interfaces/msg/runtime_event.hpp>
#include <ai_robot_runtime_interfaces/msg/trace_header.hpp>
#include <ai_robot_runtime_interfaces/runtime_event_identity.hpp>
#include <ai_robot_runtime_interfaces/srv/runtime_query.hpp>
#include <rclcpp/rclcpp.hpp>

#include <chrono>
#include <cstdint>
#include <memory>
#include <string>
#include <thread>

namespace service_runtime_demo
{

class ServiceServerNode final : public rclcpp::Node
{
public:
  using RuntimeEvent = ai_robot_runtime_interfaces::msg::RuntimeEvent;
  using RuntimeQuery = ai_robot_runtime_interfaces::srv::RuntimeQuery;
  using TraceHeader = ai_robot_runtime_interfaces::msg::TraceHeader;

  ServiceServerNode()
  : Node("service_runtime_server")
  {
    runtime_events_enabled_ = this->declare_parameter<bool>("runtime_events_enabled", true);
    event_publisher_ = this->create_publisher<RuntimeEvent>("/runtime/events", rclcpp::QoS(100));
    service_ = this->create_service<RuntimeQuery>(
      "/runtime/query",
      [this](
        const std::shared_ptr<RuntimeQuery::Request> request,
        std::shared_ptr<RuntimeQuery::Response> response) {
        handle_request(request, response);
      });
  }

private:
  static int64_t steady_now_ns()
  {
    const auto now = std::chrono::steady_clock::now().time_since_epoch();
    return std::chrono::duration_cast<std::chrono::nanoseconds>(now).count();
  }

  void handle_request(
    const std::shared_ptr<RuntimeQuery::Request> & request,
    const std::shared_ptr<RuntimeQuery::Response> & response)
  {
    publish_event(request->header, "service_receive", request->payload_id, request->requested_delay_ms);
    const int64_t start_ns = steady_now_ns();
    publish_event(
      request->header, "service_process_start", request->payload_id, request->requested_delay_ms,
      start_ns);
    std::this_thread::sleep_for(std::chrono::milliseconds(request->requested_delay_ms));
    const int64_t end_ns = steady_now_ns();
    publish_event(
      request->header, "service_process_end", request->payload_id, request->requested_delay_ms,
      end_ns);

    response->header = request->header;
    response->header.source_node = this->get_name();
    response->header.stage = "service_response";
    response->header.timestamp_ns = end_ns;
    response->payload_id = request->payload_id;
    response->success = true;
    response->server_start_timestamp_ns = start_ns;
    response->server_end_timestamp_ns = end_ns;
    publish_event(
      response->header, "service_response", request->payload_id, request->requested_delay_ms,
      end_ns);
  }

  void publish_event(
    const TraceHeader & source_header,
    const std::string & stage,
    const std::string & payload_id,
    const int64_t delay_ms,
    const int64_t timestamp_ns = 0)
  {
    if (!runtime_events_enabled_) {
      return;
    }
    RuntimeEvent event;
    event.header = source_header;
    event.header.source_node = this->get_name();
    event.header.stage = stage;
    event.header.timestamp_ns = timestamp_ns == 0 ? steady_now_ns() : timestamp_ns;
    event.event_name = stage;
    event.event_type = "service_server";
    ai_robot_runtime_interfaces::populate_runtime_identity(event, "monotonic");
    event.extra_json =
      "{\"payload_id\":\"" + payload_id + "\",\"requested_delay_ms\":" +
      std::to_string(delay_ms) + "}";
    event_publisher_->publish(event);
  }

  rclcpp::Service<RuntimeQuery>::SharedPtr service_;
  rclcpp::Publisher<RuntimeEvent>::SharedPtr event_publisher_;
  bool runtime_events_enabled_{true};
};

}  // namespace service_runtime_demo

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<service_runtime_demo::ServiceServerNode>());
  rclcpp::shutdown();
  return 0;
}
