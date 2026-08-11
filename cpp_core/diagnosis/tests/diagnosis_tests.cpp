#include "robotraceopt/diagnosis/diagnosis.hpp"

#include <algorithm>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace diagnosis = robotraceopt::diagnosis;

namespace {

int failures = 0;

void check(bool condition, const char* expression, const char* file, int line) {
    if (!condition) {
        ++failures;
        std::cerr << file << ':' << line << ": check failed: " << expression << '\n';
    }
}

#define CHECK(expression) check(static_cast<bool>(expression), #expression, __FILE__, __LINE__)

template <class Function>
void check_invalid_argument(Function&& function, const std::string& message_fragment) {
    try {
        function();
        CHECK(false);
    } catch (const std::invalid_argument& error) {
        CHECK(std::string(error.what()).find(message_fragment) != std::string::npos);
    } catch (...) {
        CHECK(false);
    }
}

diagnosis::NormalizedEvent event(
    std::string event_id,
    std::string source,
    std::int64_t timestamp_ns,
    std::int64_t pid,
    std::int64_t tid,
    std::string trace_id = "",
    std::int64_t sequence_id = 0,
    std::string stage = "",
    std::string clock_id = "monotonic",
    std::string host_id = "host-a") {
    diagnosis::NormalizedEvent result;
    result.event_id = std::move(event_id);
    result.source = std::move(source);
    result.event_type = stage.empty() ? "callback_start" : stage;
    result.timestamp_ns = timestamp_ns;
    result.clock_id = std::move(clock_id);
    result.trace_id = std::move(trace_id);
    result.sequence_id = sequence_id;
    result.stage = std::move(stage);
    result.pid = pid;
    result.tid = tid;
    result.host_id = std::move(host_id);
    result.provenance.emplace("source_file", std::string("fixture.jsonl"));
    return result;
}

diagnosis::StageWindow window(
    int index, std::string stage, std::string trace_id = "trace-1") {
    diagnosis::StageWindow result;
    result.window_id = "window:" + std::to_string(index);
    result.trace_id = std::move(trace_id);
    result.sequence_id = 1;
    result.stage = std::move(stage);
    result.source_node = "fixture";
    result.pid = 10;
    result.tids = {11};
    result.host_id = "host-a";
    result.clock_id = "monotonic";
    result.start_ns = index * 100;
    result.end_ns = index * 100 + 99;
    result.start_event_id = "runtime:" + std::to_string(index);
    result.end_event_id = result.start_event_id;
    return result;
}

std::vector<diagnosis::StageWindow> service_windows() {
    const std::vector<std::string> stages{
        "query_sent",
        "service_receive",
        "service_process_start",
        "service_process_end",
        "service_response",
        "response_received",
    };
    std::vector<diagnosis::StageWindow> result;
    for (std::size_t index = 0; index < stages.size(); ++index) {
        result.push_back(window(static_cast<int>(index) + 1, stages[index]));
    }
    return result;
}

diagnosis::AssociationDecision accepted_for(
    const diagnosis::NormalizedEvent& source_event,
    const diagnosis::StageWindow& target) {
    diagnosis::AssociationDecision result;
    result.event_id = source_event.event_id;
    result.status = diagnosis::AssociationStatus::Accepted;
    result.reason_code = "fixture_match";
    result.source = source_event.source;
    result.event_type = source_event.event_type;
    result.trace_id = target.trace_id;
    result.sequence_id = target.sequence_id;
    result.stage = target.stage;
    result.window_id = target.window_id;
    return result;
}

void test_stage_windows() {
    auto start = event(
        "a-start", "runtime_event", 100, 10, 11, "trace-a", 1, "planner_start");
    start.attributes.emplace("source_node", std::string("planner"));
    auto end = event(
        "a-end", "runtime_event", 200, 10, 11, "trace-a", 1, "planner_end");
    end.attributes.emplace("duration_ns", std::int64_t{25});
    const auto windows = diagnosis::build_stage_windows({start, end});
    CHECK(windows.size() == 2);
    CHECK(windows[0].start_ns == 100);
    CHECK(windows[0].end_ns == 200);
    CHECK(windows[0].source_node == "planner");
    CHECK(windows[0].end_event_id == "a-end");
    CHECK(windows[1].end_ns == 225);
    CHECK(windows[0].contains(100));
    CHECK(windows[0].contains(200));

    auto incomplete = event("missing", "runtime_event", 100, 10, 11, "", 0, "planner");
    check_invalid_argument(
        [&] { (void)diagnosis::build_stage_windows({incomplete}); }, "incomplete RuntimeEvent");

    auto bad_duration = start;
    bad_duration.event_id = "bad-duration";
    bad_duration.attributes["duration_ns"] = true;
    check_invalid_argument(
        [&] { (void)diagnosis::build_stage_windows({bad_duration}); }, "invalid duration_ns");
    check_invalid_argument(
        [&] { (void)diagnosis::build_stage_windows({bad_duration, end}); },
        "invalid duration_ns");

    auto duplicate = start;
    check_invalid_argument(
        [&] { (void)diagnosis::build_stage_windows({start, duplicate}); },
        "duplicate RuntimeEvent");

    auto ignored = event("not-runtime", "ebpf", 1, 0, 0);
    CHECK(diagnosis::build_stage_windows({ignored}).empty());
}

std::vector<diagnosis::StageWindow> overlapping_windows() {
    auto runtime_a_start = event(
        "a-start", "runtime_event", 100, 10, 11, "trace-a", 1, "planner_start");
    auto runtime_a_end = event(
        "a-end", "runtime_event", 200, 10, 11, "trace-a", 1, "planner_end");
    auto runtime_b_start = event(
        "b-start", "runtime_event", 120, 10, 12, "trace-b", 2, "planner_start");
    auto runtime_b_end = event(
        "b-end", "runtime_event", 220, 10, 12, "trace-b", 2, "planner_end");
    return diagnosis::build_stage_windows(
        {runtime_a_start, runtime_a_end, runtime_b_start, runtime_b_end});
}

void test_association() {
    const auto windows = overlapping_windows();
    const auto exact = diagnosis::associate_system_event(
        event("callback", "ros2_tracing", 150, 10, 11), windows);
    CHECK(exact.status == diagnosis::AssociationStatus::Accepted);
    CHECK(exact.reason_code == "pid_tid_time_match");
    CHECK(exact.trace_id == "trace-a");
    CHECK(exact.stage == "planner_start");
    CHECK(exact.score == 2);

    const auto ambiguous = diagnosis::associate_system_event(
        event("worker", "ros2_tracing", 150, 10, 99), windows);
    CHECK(ambiguous.status == diagnosis::AssociationStatus::Ambiguous);
    CHECK(ambiguous.reason_code == "multiple_equal_candidates");
    CHECK(ambiguous.candidate_count == 2);
    CHECK(ambiguous.trace_id.empty());

    const auto unmatched = diagnosis::associate_system_event(
        event("other-process", "ros2_tracing", 150, 999, 999), windows);
    CHECK(unmatched.status == diagnosis::AssociationStatus::Unmatched);
    CHECK(unmatched.reason_code == "no_process_time_candidate");

    const auto wrong_clock = diagnosis::associate_system_event(
        event("wrong-clock", "ros2_tracing", 150, 10, 11, "", 0, "", "realtime"),
        windows);
    CHECK(wrong_clock.status == diagnosis::AssociationStatus::Rejected);
    CHECK(wrong_clock.reason_code == "clock_domain_mismatch");

    auto metadata = event("metadata", "ros2_tracing", 150, 10, 11);
    metadata.event_type = "ros2:rcl_timer_init";
    const auto metadata_result = diagnosis::associate_system_event(metadata, windows);
    CHECK(metadata_result.status == diagnosis::AssociationStatus::Unmatched);
    CHECK(metadata_result.reason_code == "topology_metadata");

    const auto baseline = diagnosis::associate_by_timestamp(
        event("baseline", "ros2_tracing", 150, 999, 999), windows);
    CHECK(baseline.status == diagnosis::AssociationStatus::Accepted);
    CHECK(baseline.reason_code == "timestamp_only_baseline");
    CHECK(!baseline.trace_id.empty());

    const auto no_windows = diagnosis::associate_system_event(
        event("empty", "ros2_tracing", 1, 1, 1), {});
    CHECK(no_windows.status == diagnosis::AssociationStatus::Rejected);
    CHECK(no_windows.reason_code == "host_mismatch");
}

void test_topology() {
    const auto& contract = diagnosis::topology_contract("W2");
    const std::vector<std::string> complete{
        "query_sent",
        "service_receive",
        "service_process_start",
        "service_process_end",
        "service_response",
        "response_received",
    };
    const auto valid = contract.validate(complete);
    CHECK(valid.status == diagnosis::TopologyStatus::Valid);
    CHECK(valid.matched_path == "request_response");

    auto missing_stages = complete;
    missing_stages.erase(missing_stages.begin() + 2);
    const auto partial = contract.validate(missing_stages);
    CHECK(partial.status == diagnosis::TopologyStatus::Partial);
    CHECK(partial.missing_expected == std::vector<std::string>{"service_process_start"});

    auto out_of_order = complete;
    std::swap(out_of_order[2], out_of_order[3]);
    const auto invalid = contract.validate(out_of_order);
    CHECK(invalid.status == diagnosis::TopologyStatus::Invalid);
    CHECK(invalid.reason_codes == std::vector<std::string>{"topology_order_violation"});
    CHECK(invalid.conflicting_stages ==
          (std::vector<std::string>{"service_process_end", "service_process_start"}));

    const auto terminal_conflict = diagnosis::topology_contract("w1").validate(
        {"can_ack_received", "can_retry_exhausted"});
    CHECK(terminal_conflict.status == diagnosis::TopologyStatus::Invalid);
    CHECK(terminal_conflict.reason_codes ==
          std::vector<std::string>{"topology_terminal_conflict"});

    check_invalid_argument(
        [] { (void)diagnosis::topology_contract("unknown"); }, "unknown topology contract");
}

void test_graph_model_constraints() {
    diagnosis::EvidenceGraph graph;
    diagnosis::EvidenceNode trace;
    trace.node_id = "trace:1";
    trace.node_type = diagnosis::NodeType::Trace;
    graph.add_node(trace);
    check_invalid_argument([&] { graph.add_node(trace); }, "duplicate evidence node");
    check_invalid_argument(
        [&] {
            graph.add_edge(
                {"trace:1", "missing", diagnosis::EdgeType::BelongsTo, "", {}});
        },
        "unknown evidence edge endpoint");
    check_invalid_argument(
        [&] {
            diagnosis::EvidenceNode replacement;
            replacement.node_id = "missing";
            graph.replace_node(std::move(replacement));
        },
        "unknown evidence node");
    CHECK(graph.nodes().size() == 1);
    CHECK(graph.edges().empty());
}

void test_graph_builder() {
    const auto windows = service_windows();
    auto callback = event("callback", "ros2_tracing", 250, 10, 11);
    callback.event_type = "ros2:callback_start";
    callback.attributes = {
        {"timestamp_ns", std::int64_t{999}},
        {"pid", std::int64_t{999}},
        {"custom", std::string("kept")},
    };
    auto background = event("background", "ros2_tracing", 250, 10, 11);
    background.event_type = "ros2:rcl_node_init";
    auto accepted = accepted_for(callback, windows[1]);
    diagnosis::AssociationDecision unassigned;
    unassigned.event_id = background.event_id;
    unassigned.status = diagnosis::AssociationStatus::Unmatched;
    unassigned.reason_code = "topology_metadata";

    const auto graph = diagnosis::build_evidence_graph(
        windows,
        {callback, background},
        {accepted, unassigned},
        diagnosis::topology_contract("w2"));
    CHECK(graph.validations().at("trace-1").status == diagnosis::TopologyStatus::Valid);
    CHECK(graph.unassigned().size() == 1);
    CHECK(graph.unassigned()[0].event_id == "background");
    CHECK(graph.nodes().count("evidence:background") == 0);
    CHECK(graph.nodes().at("evidence:callback").node_type == diagnosis::NodeType::RosCallback);
    CHECK(std::get<std::int64_t>(
              graph.nodes().at("evidence:callback").attributes.at("timestamp_ns")) == 250);
    CHECK(std::get<std::int64_t>(
              graph.nodes().at("evidence:callback").source_attributes.at("timestamp_ns")) == 999);
    CHECK(std::any_of(graph.edges().begin(), graph.edges().end(), [](const auto& edge) {
        return edge.edge_type == diagnosis::EdgeType::ExecutedBy &&
               edge.source_id == "window:2" && edge.target_id == "evidence:callback";
    }));

    check_invalid_argument(
        [&] {
            (void)diagnosis::build_evidence_graph(
                windows, {callback}, {}, diagnosis::topology_contract("w2"));
        },
        "coverage mismatch");

    auto wrong_target = accepted;
    wrong_target.sequence_id = 99;
    check_invalid_argument(
        [&] {
            (void)diagnosis::build_evidence_graph(
                windows, {callback}, {wrong_target}, diagnosis::topology_contract("w2"));
        },
        "target mismatch");

    auto mixed_windows = windows;
    mixed_windows.back().sequence_id = 2;
    check_invalid_argument(
        [&] {
            (void)diagnosis::build_evidence_graph(
                mixed_windows, {}, {}, diagnosis::topology_contract("w2"));
        },
        "inconsistent trace identity");

    auto partial_windows = windows;
    partial_windows.erase(partial_windows.begin() + 2);
    const auto partial_graph = diagnosis::build_evidence_graph(
        partial_windows, {}, {}, diagnosis::topology_contract("w2"));
    const auto missing = partial_graph.nodes().find("missing:trace-1:service_process_start");
    CHECK(missing != partial_graph.nodes().end());
    CHECK(missing->second.evidence_state == "missing");
    CHECK(std::any_of(
        partial_graph.edges().begin(), partial_graph.edges().end(), [](const auto& edge) {
            return edge.edge_type == diagnosis::EdgeType::MissingExpected;
        }));

    auto conflicting = windows;
    std::swap(conflicting[2].stage, conflicting[3].stage);
    const auto conflict_graph = diagnosis::build_evidence_graph(
        conflicting, {}, {}, diagnosis::topology_contract("w2"));
    CHECK(std::any_of(
        conflict_graph.edges().begin(), conflict_graph.edges().end(), [](const auto& edge) {
            return edge.edge_type == diagnosis::EdgeType::Contradicts &&
                   edge.reason_code == "topology_order_violation";
        }));
}

void test_evidence_type_mapping() {
    struct TestCase {
        const char* id;
        const char* event_type;
        const char* source;
        diagnosis::NodeType expected;
    };
    const std::vector<TestCase> cases{
        {"callback", "ros2:callback_start", "ros2_tracing", diagnosis::NodeType::RosCallback},
        {"dispatch", "ros_callback_dispatch_bound", "derived_fusion", diagnosis::NodeType::RosCallback},
        {"delivery", "dds_delivery_bound", "derived_fusion", diagnosis::NodeType::DdsCommunication},
        {"dds", "ros2:rmw_publish", "ros2_tracing", diagnosis::NodeType::DdsCommunication},
        {"syscall", "syscall_interval", "ebpf", diagnosis::NodeType::SyscallInterval},
        {"schedule", "scheduling_interval", "ebpf", diagnosis::NodeType::SchedulingInterval},
        {"command", "can_command", "can_ack", diagnosis::NodeType::CanCommand},
        {"ack", "can_ack_received", "can_ack", diagnosis::NodeType::AckTerminal},
    };
    const auto windows = service_windows();
    for (const auto& test_case : cases) {
        auto source_event = event(test_case.id, test_case.source, 250, 10, 11);
        source_event.event_type = test_case.event_type;
        const auto graph = diagnosis::build_evidence_graph(
            windows,
            {source_event},
            {accepted_for(source_event, windows[1])},
            diagnosis::topology_contract("w2"));
        CHECK(graph.nodes().at("evidence:" + std::string(test_case.id)).node_type ==
              test_case.expected);
    }
}

void run(const char* name, const std::function<void()>& function) {
    const auto before = failures;
    try {
        function();
    } catch (const std::exception& error) {
        ++failures;
        std::cerr << name << ": unexpected exception: " << error.what() << '\n';
    } catch (...) {
        ++failures;
        std::cerr << name << ": unexpected non-standard exception\n";
    }
    if (failures == before) {
        std::cout << "[PASS] " << name << '\n';
    } else {
        std::cout << "[FAIL] " << name << '\n';
    }
}

}  // namespace

int main() {
    run("stage windows", test_stage_windows);
    run("association", test_association);
    run("topology", test_topology);
    run("graph model constraints", test_graph_model_constraints);
    run("graph builder", test_graph_builder);
    run("evidence type mapping", test_evidence_type_mapping);
    if (failures != 0) {
        std::cerr << failures << " assertion(s) failed\n";
        return 1;
    }
    std::cout << "All diagnosis tests passed\n";
    return 0;
}
