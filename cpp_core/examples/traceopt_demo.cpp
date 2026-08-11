#include "robotraceopt/diagnosis/diagnosis.hpp"
#include "robotraceopt/optimizer/candidate_sampler.hpp"
#include "robotraceopt/optimizer/runtime_objective.hpp"
#include "robotraceopt/planner/clients.hpp"
#include "robotraceopt/planner/model_admission.hpp"

#include <cstdint>
#include <iostream>
#include <string>
#include <variant>
#include <vector>

namespace diagnosis = robotraceopt::diagnosis;
namespace optimizer = robotraceopt::optimizer;
namespace planner = robotraceopt::planner;

namespace {

diagnosis::NormalizedEvent runtime_event(
    std::string id,
    std::string stage,
    std::int64_t timestamp_ns) {
    diagnosis::NormalizedEvent event;
    event.event_id = std::move(id);
    event.source = "runtime_event";
    event.event_type = stage;
    event.timestamp_ns = timestamp_ns;
    event.clock_id = "monotonic";
    event.trace_id = "demo-trace";
    event.sequence_id = 1;
    event.stage = std::move(stage);
    event.pid = 100;
    event.tid = 101;
    event.host_id = "demo-host";
    return event;
}

}  // namespace

int main() {
    const std::vector<diagnosis::NormalizedEvent> runtime_events{
        runtime_event("event-1", "query_sent", 100),
        runtime_event("event-2", "service_receive", 200),
        runtime_event("event-3", "service_process_start", 300),
        runtime_event("event-4", "service_process_end", 400),
        runtime_event("event-5", "service_response", 500),
        runtime_event("event-6", "response_received", 600),
    };
    const auto windows = diagnosis::build_stage_windows(runtime_events);

    diagnosis::NormalizedEvent callback;
    callback.event_id = "callback-1";
    callback.source = "ros2_tracing";
    callback.event_type = "ros2:callback_start";
    callback.timestamp_ns = 250;
    callback.clock_id = "monotonic";
    callback.pid = 100;
    callback.tid = 101;
    callback.host_id = "demo-host";

    const auto association = diagnosis::associate_system_event(callback, windows);
    const auto graph = diagnosis::build_evidence_graph(
        windows,
        {callback},
        {association},
        diagnosis::topology_contract("w2"));

    optimizer::RuntimeReport report;
    report.schema_version = "demo-runtime-report/v1";
    report.metrics_ns = {{"end_to_end", {{"p95", 500.0}}}};
    report.complete_trace_rate = 1.0;
    report.development_only = false;
    report.formal_inference_allowed = true;
    const auto objective = optimizer::runtime_objective(report, "end_to_end", "p95");
    const auto candidates = optimizer::sample_candidates(
        optimizer::DiagnosisCause::ExecutorQueueing, 4, 0);

    planner::ModelRequest request;
    request.request_id = "demo-request";
    request.session_id = "demo-session";
    request.trace_id = "demo-trace";
    request.oracle_id = "demo-oracle";
    request.sequence_id = 1;
    request.observation_timestamp_ns = 1'000'000'000;
    request.created_timestamp_ns = 1'010'000'000;
    request.deadline_ns = 1'250'000'000;
    request.input_fingerprint = "demo-frame-fingerprint";
    planner::ModelAdmission admission(100, 1'000, 3);
    const auto admission_reason = admission.admit(request, 1'010'000'000);
    const auto planner_result = planner::MockPlannerClient{}.plan_with_request(request);
    const auto decision_reason = planner_result.decision.has_value()
        ? planner::validate_decision(*planner_result.decision)
        : std::string{"planner_result_missing"};

    std::cout << "stage_windows=" << windows.size() << '\n'
              << "association=" << diagnosis::to_string(association.status) << '\n'
              << "evidence_nodes=" << graph.nodes().size() << '\n'
              << "objective_ns=" << objective.objective_value_ns << '\n'
              << "candidate_count=" << candidates.size() << '\n'
              << "planner=" << (planner_result.succeeded() ? "accepted" : "rejected")
              << '\n';

    const bool valid =
        windows.size() == 6 &&
        association.status == diagnosis::AssociationStatus::Accepted &&
        graph.validations().at("demo-trace").status == diagnosis::TopologyStatus::Valid &&
        objective.formal_optimization_allowed &&
        candidates.size() == 4 &&
        admission_reason.empty() &&
        planner_result.succeeded() &&
        decision_reason.empty();
    return valid ? 0 : 1;
}
