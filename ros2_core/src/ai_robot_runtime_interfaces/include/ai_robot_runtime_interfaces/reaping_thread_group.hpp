#ifndef AI_ROBOT_RUNTIME_INTERFACES__REAPING_THREAD_GROUP_HPP_
#define AI_ROBOT_RUNTIME_INTERFACES__REAPING_THREAD_GROUP_HPP_

#include <atomic>
#include <cstddef>
#include <functional>
#include <memory>
#include <mutex>
#include <thread>
#include <utility>
#include <vector>

namespace ai_robot_runtime_interfaces
{

/// Owns short-lived worker threads and joins finished ones as it goes.
///
/// A plain `std::vector<std::thread>` joined only in the destructor grows for
/// the whole run: every completed command keeps a joinable handle and its stack
/// until shutdown, so memory and thread limits drift with command count and a
/// long experiment measures a system that keeps changing.
///
/// `spawn` reaps before it appends, so the group stays proportional to the work
/// actually in flight. A worker may spawn again (the CAN retry path does); that
/// is safe because `spawn` never joins the thread it is called from — only
/// workers that have already returned. `close` stops new work before joining,
/// so a worker cannot re-enter the group while the owner is shutting down.
class ReapingThreadGroup
{
public:
  ReapingThreadGroup() = default;
  ~ReapingThreadGroup() { close(); }

  ReapingThreadGroup(const ReapingThreadGroup &) = delete;
  ReapingThreadGroup & operator=(const ReapingThreadGroup &) = delete;

  /// Start a worker. Ignored once the group is closed.
  void spawn(std::function<void()> body)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (closed_.load()) {
      return;
    }
    reap_finished();
    auto done = std::make_shared<std::atomic_bool>(false);
    workers_.push_back(Worker{
      std::thread([body = std::move(body), done]() {
        try {
          body();
        } catch (...) {
          done->store(true);
          throw;
        }
        done->store(true);
      }),
      done});
  }

  /// Refuse further work, then join everything still running. Idempotent.
  void close()
  {
    closed_.store(true);
    std::vector<Worker> pending;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      pending.swap(workers_);
    }
    // Join outside the lock: a worker blocked in spawn() must be able to
    // observe `closed_` and return, otherwise this thread waits forever.
    for (auto & worker : pending) {
      if (worker.thread.joinable()) {
        worker.thread.join();
      }
    }
  }

  /// Workers retained right now, after reaping the finished ones.
  std::size_t size()
  {
    std::lock_guard<std::mutex> lock(mutex_);
    reap_finished();
    return workers_.size();
  }

private:
  struct Worker
  {
    std::thread thread;
    std::shared_ptr<std::atomic_bool> done;
  };

  // Requires mutex_. A finished worker still needs its join, so drop it here
  // instead of letting the vector accumulate handles.
  void reap_finished()
  {
    for (auto iterator = workers_.begin(); iterator != workers_.end();) {
      if (iterator->done->load()) {
        if (iterator->thread.joinable()) {
          iterator->thread.join();
        }
        iterator = workers_.erase(iterator);
      } else {
        ++iterator;
      }
    }
  }

  std::mutex mutex_;
  std::atomic_bool closed_{false};
  std::vector<Worker> workers_;
};

}  // namespace ai_robot_runtime_interfaces

#endif  // AI_ROBOT_RUNTIME_INTERFACES__REAPING_THREAD_GROUP_HPP_
