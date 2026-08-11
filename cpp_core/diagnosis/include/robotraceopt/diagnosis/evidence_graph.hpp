#pragma once

#include "robotraceopt/diagnosis/association.hpp"
#include "robotraceopt/diagnosis/topology_contract.hpp"

#include <map>
#include <string>
#include <string_view>
#include <vector>

namespace robotraceopt::diagnosis {

enum class NodeType {
    Trace,
    StageWindow,
    RosCallback,
    DdsCommunication,
    SyscallInterval,
    SchedulingInterval,
    CanCommand,
    AckTerminal,
    CandidateCause,
};

enum class EdgeType {
    BelongsTo,
    Precedes,
    Overlaps,
    ExecutedBy,
    Supports,
    Contradicts,
    MissingExpected,
};

[[nodiscard]] std::string_view to_string(NodeType type) noexcept;
[[nodiscard]] std::string_view to_string(EdgeType type) noexcept;

struct EvidenceNode {
    std::string node_id;
    NodeType node_type{NodeType::Trace};
    std::string trace_id;
    std::string stage;
    std::string evidence_state{"observed"};
    AttributeMap attributes;
    AttributeMap source_attributes;
    AttributeMap provenance;
};

struct EvidenceEdge {
    std::string source_id;
    std::string target_id;
    EdgeType edge_type{EdgeType::BelongsTo};
    std::string reason_code;
    AttributeMap attributes;
};

struct UnassignedEvidence {
    std::string event_id;
    AssociationStatus status{AssociationStatus::Unmatched};
    std::string reason_code;
    std::string source;
    std::string event_type;
    AttributeMap provenance;
};

class EvidenceGraph {
public:
    // Mutation is strongly checked. Failures throw std::invalid_argument and do
    // not modify the graph.
    void add_node(EvidenceNode node);
    void replace_node(EvidenceNode node);
    void add_edge(EvidenceEdge edge);
    void add_unassigned(UnassignedEvidence evidence);
    void set_validation(std::string trace_id, TopologyValidation validation);

    [[nodiscard]] const std::map<std::string, EvidenceNode>& nodes() const noexcept {
        return nodes_;
    }
    [[nodiscard]] const std::vector<EvidenceEdge>& edges() const noexcept { return edges_; }
    [[nodiscard]] const std::vector<UnassignedEvidence>& unassigned() const noexcept {
        return unassigned_;
    }
    [[nodiscard]] const std::map<std::string, TopologyValidation>& validations() const noexcept {
        return validations_;
    }

private:
    std::map<std::string, EvidenceNode> nodes_;
    std::vector<EvidenceEdge> edges_;
    std::vector<UnassignedEvidence> unassigned_;
    std::map<std::string, TopologyValidation> validations_;
};

// Enforces one unique decision per system event, unique window ids, consistent
// sequence identity per trace, and exact accepted-decision target identity.
// Violations throw std::invalid_argument; no partial graph is returned.
[[nodiscard]] EvidenceGraph build_evidence_graph(
    const std::vector<StageWindow>& windows,
    const std::vector<NormalizedEvent>& system_events,
    const std::vector<AssociationDecision>& decisions,
    const TopologyContract& contract);

}  // namespace robotraceopt::diagnosis
