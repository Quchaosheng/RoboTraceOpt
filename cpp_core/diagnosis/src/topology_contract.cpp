#include "robotraceopt/diagnosis/topology_contract.hpp"

#include <algorithm>
#include <cctype>
#include <map>
#include <set>
#include <stdexcept>
#include <tuple>
#include <utility>

namespace robotraceopt::diagnosis {
namespace {

std::vector<std::string> w1_prefix() {
    return {
        "camera_publish",
        "planner_receive",
        "planner_process_start",
        "planner_process_end",
        "planner_publish",
        "action_receive",
        "action_execute_start",
        "action_execute_end",
        "can_receive",
        "can_encode_start",
        "can_encode_end",
        "can_frame_sent",
    };
}

std::vector<std::string> with_suffix(
    std::vector<std::string> prefix, std::initializer_list<const char*> suffix) {
    for (const auto* stage : suffix) {
        prefix.emplace_back(stage);
    }
    return prefix;
}

const std::map<std::string, TopologyContract>& contracts() {
    static const std::map<std::string, TopologyContract> value{
        {"w1",
         TopologyContract{
             "w1",
             {
                 {"ack_received",
                  with_suffix(w1_prefix(), {"can_ack_wait_start", "can_ack_received"})},
                 {"retry_exhausted",
                  with_suffix(w1_prefix(), {"can_ack_wait_start", "can_retry_exhausted"})},
                 {"send_failed", with_suffix(w1_prefix(), {"can_frame_send_failed"})},
             }}},
        {"w2",
         TopologyContract{
             "w2",
             {{"request_response",
               {"query_sent",
                "service_receive",
                "service_process_start",
                "service_process_end",
                "service_response",
                "response_received"}}}}},
    };
    return value;
}

}  // namespace

std::string_view to_string(TopologyStatus status) noexcept {
    switch (status) {
        case TopologyStatus::Valid:
            return "valid";
        case TopologyStatus::Partial:
            return "partial";
        case TopologyStatus::Invalid:
            return "invalid";
    }
    return "invalid";
}

TopologyContract::TopologyContract(std::string workload_id, std::vector<TopologyPath> paths)
    : workload_id_(std::move(workload_id)), paths_(std::move(paths)) {
    if (workload_id_.empty()) {
        throw std::invalid_argument("topology workload id must not be empty");
    }
    if (paths_.empty()) {
        throw std::invalid_argument("topology contract must contain at least one path");
    }
    std::set<std::string> names;
    for (const auto& path : paths_) {
        if (path.name.empty() || path.required_stages.empty()) {
            throw std::invalid_argument("topology path name and stages must not be empty");
        }
        if (!names.emplace(path.name).second) {
            throw std::invalid_argument("duplicate topology path: " + path.name);
        }
        if (std::any_of(path.required_stages.begin(), path.required_stages.end(),
                        [](const auto& stage) { return stage.empty(); })) {
            throw std::invalid_argument("topology stage must not be empty: " + path.name);
        }
        const std::set<std::string> unique_stages(
            path.required_stages.begin(), path.required_stages.end());
        if (unique_stages.size() != path.required_stages.size()) {
            throw std::invalid_argument("duplicate topology stage: " + path.name);
        }
    }
}

TopologyValidation TopologyContract::evaluate_path(
    const std::vector<std::string>& observed, const TopologyPath& path) {
    std::map<std::string, std::size_t> stage_index;
    for (std::size_t index = 0; index < path.required_stages.size(); ++index) {
        stage_index.emplace(path.required_stages[index], index);
    }
    std::vector<std::string> admitted;
    for (const auto& stage : observed) {
        if (stage_index.count(stage) != 0) {
            admitted.push_back(stage);
        }
    }

    std::vector<std::string> conflict;
    for (std::size_t index = 1; index < admitted.size(); ++index) {
        if (stage_index.at(admitted[index]) < stage_index.at(admitted[index - 1])) {
            conflict = {admitted[index - 1], admitted[index]};
            break;
        }
    }
    std::set<std::string> admitted_set(admitted.begin(), admitted.end());
    std::vector<std::string> missing;
    for (const auto& required : path.required_stages) {
        if (admitted_set.count(required) == 0) {
            missing.push_back(required);
        }
    }
    if (!conflict.empty()) {
        return {TopologyStatus::Invalid,
                path.name,
                std::move(missing),
                std::move(conflict),
                {"topology_order_violation"}};
    }
    if (!missing.empty()) {
        return {TopologyStatus::Partial,
                path.name,
                std::move(missing),
                {},
                {"topology_stage_missing"}};
    }
    return {TopologyStatus::Valid, path.name, {}, {}, {}};
}

TopologyValidation TopologyContract::validate(
    const std::vector<std::string>& observed_stages) const {
    std::set<std::string> terminal_set;
    for (const auto& path : paths_) {
        terminal_set.emplace(path.required_stages.back());
    }
    std::vector<std::string> observed_terminals;
    std::set<std::string> seen_terminals;
    for (const auto& stage : observed_stages) {
        if (terminal_set.count(stage) != 0 && seen_terminals.emplace(stage).second) {
            observed_terminals.push_back(stage);
        }
    }
    if (observed_terminals.size() > 1) {
        return {TopologyStatus::Invalid,
                "",
                {},
                std::move(observed_terminals),
                {"topology_terminal_conflict"}};
    }

    std::vector<TopologyValidation> evaluations;
    for (const auto& path : paths_) {
        if (observed_terminals.empty() || path.required_stages.back() == observed_terminals[0]) {
            evaluations.push_back(evaluate_path(observed_stages, path));
        }
    }
    const auto valid = std::find_if(evaluations.begin(), evaluations.end(), [](const auto& item) {
        return item.status == TopologyStatus::Valid;
    });
    if (valid != evaluations.end()) {
        return *valid;
    }
    return *std::min_element(evaluations.begin(), evaluations.end(), [](const auto& left,
                                                                        const auto& right) {
        return std::tuple{left.status == TopologyStatus::Invalid,
                          left.missing_expected.size(),
                          left.conflicting_stages.size(),
                          left.matched_path} <
               std::tuple{right.status == TopologyStatus::Invalid,
                          right.missing_expected.size(),
                          right.conflicting_stages.size(),
                          right.matched_path};
    });
}

const TopologyContract& topology_contract(std::string_view workload_id) {
    std::string key(workload_id);
    std::transform(key.begin(), key.end(), key.begin(), [](unsigned char value) {
        return static_cast<char>(std::tolower(value));
    });
    const auto found = contracts().find(key);
    if (found == contracts().end()) {
        throw std::invalid_argument("unknown topology contract: " + std::string(workload_id));
    }
    return found->second;
}

}  // namespace robotraceopt::diagnosis
