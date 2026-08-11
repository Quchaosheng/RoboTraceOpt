#pragma once

#include <string>
#include <string_view>
#include <vector>

namespace robotraceopt::diagnosis {

enum class TopologyStatus { Valid, Partial, Invalid };

[[nodiscard]] std::string_view to_string(TopologyStatus status) noexcept;

struct TopologyPath {
    std::string name;
    std::vector<std::string> required_stages;
};

struct TopologyValidation {
    TopologyStatus status{TopologyStatus::Invalid};
    std::string matched_path;
    std::vector<std::string> missing_expected;
    std::vector<std::string> conflicting_stages;
    std::vector<std::string> reason_codes;
};

class TopologyContract {
public:
    TopologyContract(std::string workload_id, std::vector<TopologyPath> paths);

    [[nodiscard]] const std::string& workload_id() const noexcept { return workload_id_; }
    [[nodiscard]] const std::vector<TopologyPath>& paths() const noexcept { return paths_; }
    [[nodiscard]] TopologyValidation validate(
        const std::vector<std::string>& observed_stages) const;

private:
    [[nodiscard]] static TopologyValidation evaluate_path(
        const std::vector<std::string>& observed, const TopologyPath& path);

    std::string workload_id_;
    std::vector<TopologyPath> paths_;
};

// Throws std::invalid_argument for an unknown workload id.
[[nodiscard]] const TopologyContract& topology_contract(std::string_view workload_id);

}  // namespace robotraceopt::diagnosis
