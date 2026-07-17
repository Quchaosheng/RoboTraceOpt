#ifndef AI_ROBOT_RUNTIME_INTERFACES__RUNTIME_EVENT_IDENTITY_HPP_
#define AI_ROBOT_RUNTIME_INTERFACES__RUNTIME_EVENT_IDENTITY_HPP_

#include <sys/syscall.h>
#include <unistd.h>

#include <cstdint>
#include <string>

#include "ai_robot_runtime_interfaces/msg/runtime_event.hpp"

namespace ai_robot_runtime_interfaces
{

inline const std::string & current_host_id()
{
  static const std::string host_id = []() {
      char hostname[256]{};
      hostname[sizeof(hostname) - 1] = '\0';
      if (::gethostname(hostname, sizeof(hostname) - 1) != 0) {
        return std::string{"unknown"};
      }
      return std::string{hostname};
    }();
  return host_id;
}

inline void populate_runtime_identity(
  msg::RuntimeEvent & event,
  const std::string & clock_id,
  const std::string & status = "observed",
  const std::string & reason_code = "")
{
  event.pid = static_cast<uint32_t>(::getpid());
  event.tid = static_cast<uint32_t>(::syscall(SYS_gettid));
  event.host_id = current_host_id();
  event.clock_id = clock_id;
  event.duration_ns = 0;
  event.status = status;
  event.reason_code = reason_code;
}

}  // namespace ai_robot_runtime_interfaces

#endif  // AI_ROBOT_RUNTIME_INTERFACES__RUNTIME_EVENT_IDENTITY_HPP_
