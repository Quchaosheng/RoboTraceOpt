#include "robotraceopt/diagnosis/evidence_graph.hpp"

#include <algorithm>
#include <cctype>
#include <map>
#include <set>
#include <stdexcept>
#include <tuple>
#include <utility>

namespace robotraceopt::diagnosis {
namespace {

std::string lower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char item) {
        return static_cast<char>(std::tolower(item));
    });
    return value;
}

bool contains(const std::string& value, const char* token) {
    return value.find(token) != std::string::npos;
}

NodeType system_node_type(const NormalizedEvent& event) {
    const auto event_type = lower(event.event_type);
    const auto source = lower(event.source);
    if (source == "derived_fusion" && event_type == "ros_callback_dispatch_bound") {
        return NodeType::RosCallback;
    }
    if (source == "derived_fusion" && event_type == "dds_delivery_bound") {
        return NodeType::DdsCommunication;
    }
    if (source == "ros2_tracing") {
        if (contains(event_type, "callback")) {
            return NodeType::RosCallback;
        }
        if (contains(event_type, "dds") || contains(event_type, "rmw") ||
            contains(event_type, "publish") || contains(event_type, "take")) {
            return NodeType::DdsCommunication;
        }
    }
    if (source == "ebpf") {
        if (contains(event_type, "syscall")) {
            return NodeType::SyscallInterval;
        }
        if (contains(event_type, "sched") || contains(event_type, "wakeup") ||
            contains(event_type, "off_cpu") || contains(event_type, "scheduling")) {
            return NodeType::SchedulingInterval;
        }
    }
    if (source == "can" || source == "socketcan" || source == "can_ack") {
        if (event_type == "can_ack_received" || event_type == "can_retry_exhausted" ||
            event_type == "can_frame_send_failed") {
            return NodeType::AckTerminal;
        }
        return NodeType::CanCommand;
    }
    throw std::invalid_argument("unsupported accepted evidence type: " + event.event_type);
}

EvidenceNode stage_node(const StageWindow& window) {
    EvidenceNode node;
    node.node_id = window.window_id;
    node.node_type = NodeType::StageWindow;
    node.trace_id = window.trace_id;
    node.stage = window.stage;
    node.attributes = {
        {"sequence_id", window.sequence_id},
        {"source_node", window.source_node},
        {"pid", window.pid},
        {"tids", window.tids},
        {"host_id", window.host_id},
        {"clock_id", window.clock_id},
        {"start_ns", window.start_ns},
        {"end_ns", window.end_ns},
    };
    node.provenance = {
        {"start_event_id", window.start_event_id}, {"end_event_id", window.end_event_id}};
    return node;
}

EvidenceNode system_node(const NormalizedEvent& event, const AssociationDecision& decision) {
    EvidenceNode node;
    node.node_id = "evidence:" + event.event_id;
    node.node_type = system_node_type(event);
    node.trace_id = decision.trace_id;
    node.stage = decision.stage;
    node.attributes = {
        {"source", event.source},
        {"event_type", event.event_type},
        {"timestamp_ns", event.timestamp_ns},
        {"pid", event.pid},
        {"tid", event.tid},
        {"host_id", event.host_id},
        {"clock_id", event.clock_id},
    };
    node.source_attributes = event.attributes;
    node.provenance = event.provenance;
    return node;
}

}  // namespace

std::string_view to_string(NodeType type) noexcept {
    switch (type) {
        case NodeType::Trace: return "Trace";
        case NodeType::StageWindow: return "StageWindow";
        case NodeType::RosCallback: return "RosCallback";
        case NodeType::DdsCommunication: return "DdsCommunication";
        case NodeType::SyscallInterval: return "SyscallInterval";
        case NodeType::SchedulingInterval: return "SchedulingInterval";
        case NodeType::CanCommand: return "CanCommand";
        case NodeType::AckTerminal: return "AckTerminal";
        case NodeType::CandidateCause: return "CandidateCause";
    }
    return "Trace";
}

std::string_view to_string(EdgeType type) noexcept {
    switch (type) {
        case EdgeType::BelongsTo: return "belongs_to";
        case EdgeType::Precedes: return "precedes";
        case EdgeType::Overlaps: return "overlaps";
        case EdgeType::ExecutedBy: return "executed_by";
        case EdgeType::Supports: return "supports";
        case EdgeType::Contradicts: return "contradicts";
        case EdgeType::MissingExpected: return "missing_expected";
    }
    return "belongs_to";
}

void EvidenceGraph::add_node(EvidenceNode node) {
    if (node.node_id.empty()) {
        throw std::invalid_argument("evidence node id must not be empty");
    }
    if (nodes_.count(node.node_id) != 0) {
        throw std::invalid_argument("duplicate evidence node: " + node.node_id);
    }
    nodes_.emplace(node.node_id, std::move(node));
}

void EvidenceGraph::replace_node(EvidenceNode node) {
    if (nodes_.count(node.node_id) == 0) {
        throw std::invalid_argument("unknown evidence node: " + node.node_id);
    }
    nodes_.at(node.node_id) = std::move(node);
}

void EvidenceGraph::add_edge(EvidenceEdge edge) {
    std::vector<std::string> missing;
    if (nodes_.count(edge.source_id) == 0) missing.push_back(edge.source_id);
    if (nodes_.count(edge.target_id) == 0) missing.push_back(edge.target_id);
    if (!missing.empty()) {
        std::string message = "unknown evidence edge endpoint:";
        for (const auto& item : missing) message += " " + item;
        throw std::invalid_argument(message);
    }
    edges_.push_back(std::move(edge));
}

void EvidenceGraph::add_unassigned(UnassignedEvidence evidence) {
    if (evidence.event_id.empty()) {
        throw std::invalid_argument("unassigned evidence event id must not be empty");
    }
    unassigned_.push_back(std::move(evidence));
}

void EvidenceGraph::set_validation(std::string trace_id, TopologyValidation validation) {
    if (trace_id.empty()) {
        throw std::invalid_argument("validation trace id must not be empty");
    }
    validations_[std::move(trace_id)] = std::move(validation);
}

EvidenceGraph build_evidence_graph(
    const std::vector<StageWindow>& windows,
    const std::vector<NormalizedEvent>& system_events,
    const std::vector<AssociationDecision>& decisions,
    const TopologyContract& contract) {
    std::map<std::string, const NormalizedEvent*> events_by_id;
    for (const auto& event : system_events) {
        if (event.event_id.empty() || !events_by_id.emplace(event.event_id, &event).second) {
            throw std::invalid_argument("duplicate or empty system event id: " + event.event_id);
        }
    }
    std::map<std::string, const AssociationDecision*> decisions_by_id;
    for (const auto& decision : decisions) {
        if (decision.event_id.empty() ||
            !decisions_by_id.emplace(decision.event_id, &decision).second) {
            throw std::invalid_argument(
                "duplicate or empty association decision: " + decision.event_id);
        }
    }
    if (events_by_id.size() != decisions_by_id.size()) {
        throw std::invalid_argument("association decision coverage mismatch");
    }
    for (const auto& [event_id, event] : events_by_id) {
        (void)event;
        if (decisions_by_id.count(event_id) == 0) {
            throw std::invalid_argument("association decision coverage mismatch: " + event_id);
        }
    }

    std::map<std::string, const StageWindow*> windows_by_id;
    std::map<std::string, std::vector<const StageWindow*>> windows_by_trace;
    for (const auto& window : windows) {
        if (window.window_id.empty() || !windows_by_id.emplace(window.window_id, &window).second) {
            throw std::invalid_argument("duplicate or empty stage window: " + window.window_id);
        }
        if (window.trace_id.empty()) {
            throw std::invalid_argument("stage window trace id must not be empty: " + window.window_id);
        }
        windows_by_trace[window.trace_id].push_back(&window);
    }

    EvidenceGraph graph;
    for (auto& [trace_id, trace_windows] : windows_by_trace) {
        std::sort(trace_windows.begin(), trace_windows.end(), [](const auto* left, const auto* right) {
            return std::tie(left->start_ns, left->window_id) <
                   std::tie(right->start_ns, right->window_id);
        });
        std::set<std::int64_t> sequences;
        for (const auto* window : trace_windows) sequences.emplace(window->sequence_id);
        if (sequences.size() != 1) {
            throw std::invalid_argument("inconsistent trace identity: " + trace_id);
        }

        const auto trace_node_id = "trace:" + trace_id;
        EvidenceNode trace_node;
        trace_node.node_id = trace_node_id;
        trace_node.node_type = NodeType::Trace;
        trace_node.trace_id = trace_id;
        trace_node.attributes.emplace("sequence_id", trace_windows.front()->sequence_id);
        graph.add_node(std::move(trace_node));

        for (const auto* window : trace_windows) {
            graph.add_node(stage_node(*window));
            graph.add_edge({window->window_id, trace_node_id, EdgeType::BelongsTo, "", {}});
        }
        for (std::size_t index = 1; index < trace_windows.size(); ++index) {
            graph.add_edge({trace_windows[index - 1]->window_id,
                            trace_windows[index]->window_id,
                            EdgeType::Precedes,
                            "",
                            {}});
        }
        std::vector<std::string> stages;
        for (const auto* window : trace_windows) stages.push_back(window->stage);
        auto validation = contract.validate(stages);
        graph.set_validation(trace_id, validation);

        for (const auto& missing_stage : validation.missing_expected) {
            const auto missing_id = "missing:" + trace_id + ":" + missing_stage;
            EvidenceNode missing;
            missing.node_id = missing_id;
            missing.node_type = NodeType::StageWindow;
            missing.trace_id = trace_id;
            missing.stage = missing_stage;
            missing.evidence_state = "missing";
            missing.attributes.emplace("reason_code", std::string("topology_stage_missing"));
            graph.add_node(std::move(missing));
            graph.add_edge({trace_node_id,
                            missing_id,
                            EdgeType::MissingExpected,
                            "topology_stage_missing",
                            {}});
        }
        if (!validation.conflicting_stages.empty()) {
            const auto reason = validation.reason_codes.empty() ? "" : validation.reason_codes[0];
            for (std::size_t index = 1; index < validation.conflicting_stages.size(); ++index) {
                const auto& source_stage = validation.conflicting_stages[index - 1];
                const auto& target_stage = validation.conflicting_stages[index];
                const auto source = std::find_if(trace_windows.begin(), trace_windows.end(),
                                                 [&](const auto* item) {
                                                     return item->stage == source_stage;
                                                 });
                const auto target = std::find_if(trace_windows.begin(), trace_windows.end(),
                                                 [&](const auto* item) {
                                                     return item->stage == target_stage;
                                                 });
                if (source == trace_windows.end() || target == trace_windows.end()) {
                    throw std::invalid_argument("topology conflict references unknown stage");
                }
                graph.add_edge(
                    {(*source)->window_id, (*target)->window_id, EdgeType::Contradicts, reason, {}});
            }
        }
    }

    for (const auto& [event_id, event] : events_by_id) {
        const auto& decision = *decisions_by_id.at(event_id);
        if (decision.status != AssociationStatus::Accepted) {
            graph.add_unassigned({event->event_id,
                                  decision.status,
                                  decision.reason_code,
                                  event->source,
                                  event->event_type,
                                  event->provenance});
            continue;
        }
        const auto found_window = windows_by_id.find(decision.window_id);
        if (found_window == windows_by_id.end()) {
            throw std::invalid_argument(
                "accepted decision references unknown window: " + decision.window_id);
        }
        const auto& window = *found_window->second;
        if (decision.trace_id != window.trace_id || decision.sequence_id != window.sequence_id ||
            decision.stage != window.stage) {
            throw std::invalid_argument("accepted decision target mismatch: " + event_id);
        }
        auto node = system_node(*event, decision);
        const auto node_id = node.node_id;
        const auto node_type = node.node_type;
        graph.add_node(std::move(node));
        if (node_type == NodeType::RosCallback) {
            graph.add_edge(
                {window.window_id, node_id, EdgeType::ExecutedBy, decision.reason_code, {}});
        } else {
            graph.add_edge(
                {node_id, window.window_id, EdgeType::Overlaps, decision.reason_code, {}});
        }
    }
    return graph;
}

}  // namespace robotraceopt::diagnosis
