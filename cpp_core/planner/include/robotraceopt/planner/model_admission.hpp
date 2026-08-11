#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <mutex>
#include <string>
#include <unordered_map>

#include "robotraceopt/planner/model_contract.hpp"

namespace robotraceopt::planner {

class ModelAdmission {
 public:
  ModelAdmission(std::int64_t dedup_window_ms,
                 std::int64_t failure_window_ms,
                 std::size_t max_failures,
                 std::int64_t max_future_skew_ms = 100);

  ModelAdmission(const ModelAdmission&) = delete;
  ModelAdmission& operator=(const ModelAdmission&) = delete;

  [[nodiscard]] std::string admit(const ModelRequest& request,
                                  std::int64_t now_ns);
  [[nodiscard]] static std::string output_allowed(const ModelRequest& request,
                                                  std::int64_t now_ns);
  [[nodiscard]] bool note_backend_failure(std::int64_t now_ns);
  [[nodiscard]] std::size_t failure_count_in_window() const;

 private:
  void purge_admitted(std::int64_t now_ns);
  void purge_failures(std::int64_t now_ns);

  std::int64_t dedup_window_ns_;
  std::int64_t failure_window_ns_;
  std::size_t max_failures_;
  std::int64_t max_future_skew_ns_;
  std::unordered_map<std::string, std::int64_t> admitted_until_ns_;
  std::deque<std::int64_t> failure_timestamps_ns_;
  mutable std::mutex mutex_;
};

}  // namespace robotraceopt::planner
