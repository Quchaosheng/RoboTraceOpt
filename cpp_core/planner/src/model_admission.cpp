#include "robotraceopt/planner/model_admission.hpp"

#include <algorithm>
#include <limits>
#include <stdexcept>

namespace robotraceopt::planner {
namespace {

constexpr std::int64_t kNanosecondsPerMillisecond = 1'000'000;

std::int64_t milliseconds_to_nanoseconds(std::int64_t milliseconds) {
  if (milliseconds < 0 ||
      milliseconds >
          std::numeric_limits<std::int64_t>::max() /
              kNanosecondsPerMillisecond) {
    throw std::invalid_argument("planner admission duration is out of range");
  }
  return milliseconds * kNanosecondsPerMillisecond;
}

std::int64_t saturating_add(std::int64_t left, std::int64_t right) noexcept {
  if (right > 0 && left > std::numeric_limits<std::int64_t>::max() - right) {
    return std::numeric_limits<std::int64_t>::max();
  }
  if (right < 0 && left < std::numeric_limits<std::int64_t>::min() - right) {
    return std::numeric_limits<std::int64_t>::min();
  }
  return left + right;
}

}  // namespace

ModelAdmission::ModelAdmission(std::int64_t dedup_window_ms,
                               std::int64_t failure_window_ms,
                               std::size_t max_failures,
                               std::int64_t max_future_skew_ms)
    : dedup_window_ns_(milliseconds_to_nanoseconds(dedup_window_ms)),
      failure_window_ns_(milliseconds_to_nanoseconds(failure_window_ms)),
      max_failures_(max_failures),
      max_future_skew_ns_(milliseconds_to_nanoseconds(max_future_skew_ms)) {
  if (dedup_window_ms <= 0 || failure_window_ms <= 0 || max_failures == 0 ||
      max_future_skew_ms < 0) {
    throw std::invalid_argument("invalid temporal admission configuration");
  }
}

std::string ModelAdmission::admit(const ModelRequest& request,
                                  std::int64_t now_ns) {
  std::lock_guard<std::mutex> lock(mutex_);
  purge_admitted(now_ns);
  if (request.trace_id.empty() || request.oracle_id.empty()) {
    return "planner_request_identity_missing";
  }
  if (request.observation_timestamp_ns <= 0) {
    return "planner_observation_timestamp_missing";
  }
  if (request.observation_timestamp_ns >
      saturating_add(now_ns, max_future_skew_ns_)) {
    return "planner_observation_timestamp_future";
  }
  if (request.expired(now_ns)) {
    return "planner_observation_expired";
  }
  if (admitted_until_ns_.find(request.request_id) != admitted_until_ns_.end()) {
    return "planner_duplicate_request";
  }
  admitted_until_ns_[request.request_id] = saturating_add(
      std::max(request.deadline_ns, now_ns), dedup_window_ns_);
  return {};
}

std::string ModelAdmission::output_allowed(const ModelRequest& request,
                                           std::int64_t now_ns) {
  if (request.expired(now_ns)) {
    return "planner_output_expired";
  }
  return {};
}

bool ModelAdmission::note_backend_failure(std::int64_t now_ns) {
  std::lock_guard<std::mutex> lock(mutex_);
  purge_failures(now_ns);
  failure_timestamps_ns_.push_back(now_ns);
  return failure_timestamps_ns_.size() >= max_failures_;
}

std::size_t ModelAdmission::failure_count_in_window() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return failure_timestamps_ns_.size();
}

void ModelAdmission::purge_admitted(std::int64_t now_ns) {
  for (auto item = admitted_until_ns_.begin(); item != admitted_until_ns_.end();) {
    if (item->second <= now_ns) {
      item = admitted_until_ns_.erase(item);
    } else {
      ++item;
    }
  }
}

void ModelAdmission::purge_failures(std::int64_t now_ns) {
  const auto cutoff_ns = saturating_add(now_ns, -failure_window_ns_);
  while (!failure_timestamps_ns_.empty() &&
         failure_timestamps_ns_.front() <= cutoff_ns) {
    failure_timestamps_ns_.pop_front();
  }
}

}  // namespace robotraceopt::planner
