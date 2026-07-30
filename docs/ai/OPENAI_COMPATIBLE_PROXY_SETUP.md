# OpenAI-Compatible Proxy Setup for the AI Planner

## Compatibility contract

The planner has one versioned BasePlannerClient contract for its mock, llm,
and deterministic replay backends. The OpenAI-compatible backend supports both
common API styles:

~~~
POST {LLM_API_BASE}/chat/completions
POST {LLM_API_BASE}/responses
Authorization: Bearer {LLM_API_KEY}
Content-Type: application/json
~~~

Select the route with LLM_API_STYLE=chat_completions or
LLM_API_STYLE=responses. Chat Completions returns
choices[0].message.content; Responses returns message output_text. In both
cases the extracted content must be a JSON object with action, target, speed,
confidence, and reason. Speed and confidence must be finite JSON numbers in
[0,1]; booleans, NaN, infinities, and out-of-range values are rejected.

Allowed actions are move_forward, turn_left, turn_right, stop, and inspect. A
stop action must have speed zero at the final CAN guard.

Use a base ending in /v1, for example https://your-proxy.example/v1. A complete
/chat/completions or /responses URL is also accepted. The
scripts/check_llm_proxy.py --list-models helper normalizes either full route
back to /models.

## Secret-safe configuration

Never put a token in YAML, launch files, Git, RuntimeEvent JSONL, recordings,
or thesis artifacts. Set it only in the shell that launches ROS 2:

~~~
export LLM_API_BASE="https://your-proxy.example/v1"
export LLM_API_KEY="replace-in-your-terminal-only"
export LLM_MODEL="the-model-name-exposed-by-your-proxy"
export LLM_API_STYLE="chat_completions"
~~~

On the X5, the interactive helper stores the same values in a root-only file
without echoing the key:

~~~
bash scripts/configure_llm_proxy.sh
source ~/.config/robotraceopt/llm_proxy.env
~~~

Run a metadata planning smoke test:

~~~
ros2 launch runtime_bringup ai_runtime.launch.py \
  planner_backend:=llm \
  llm_api_style:=chat_completions \
  llm_vision_mode:=metadata \
  llm_timeout_s:=3.0 \
  fallback_to_mock:=false
~~~

For a genuinely multimodal endpoint, the camera publisher must provide a real
JPEG, PNG, or WebP byte payload:

~~~
ros2 launch runtime_bringup ai_runtime.launch.py \
  planner_backend:=llm \
  llm_vision_mode:=payload_base64 \
  llm_max_image_bytes:=1000000 \
  fallback_to_mock:=false
~~~

The mock camera emits synthetic bytes and encoding=mock; it is intentionally
rejected by payload_base64. This prevents a result from being mislabeled as a
vision-planning experiment.

## Execution boundary

fallback_to_mock remains a deprecated compatibility parameter, but it is
ignored for planner_backend:=llm. Missing configuration, provider errors,
timeouts, connection resets, invalid JSON, stale observations, repeated
request identities, and invalid replay decisions all end in
planner_command_abstained; they do not publish a PlannerCommand. The only way
to generate mock movement is the explicit planner_backend:=mock experiment
setting.

The node gives every request a session/request identity, observation timestamp,
TTL/deadline, input fingerprint, prompt version, and output-schema version.
It checks freshness before inference and again before publication. The final
CAN boundary independently enforces action allowlisting, finite/ranged speed,
stop speed, timestamp TTL, and trace_id + oracle_id + sequence_id
deduplication.

model_queue_delay_ms is a deterministic F7-style pre-inference queue hook; an
expired queued observation emits planner_queue_deadline_exceeded. A delayed
provider reply that misses the observation deadline emits planner_output_stale
(F9-style). Repeated backend failures inside model_failure_window_ms emit
planner_fallback_storm after model_failure_storm_count failures (F10-style),
while every failed request still abstains individually.

## Deterministic recording and replay

Enable append-only normalized decision records for a bounded run:

~~~
ros2 launch runtime_bringup ai_runtime.launch.py \
  planner_backend:=llm \
  model_record_path:=data/raw/ai/run_01/planner_decisions.jsonl
~~~

The record contains request/session identity, timestamps, deadline, input and
response fingerprints, versions, normalized decision, backend, latency, and
stable error code. It intentionally excludes API keys, endpoint URL, image
payload, and image path. Re-run the same input contract without calling a
provider:

~~~
ros2 launch runtime_bringup ai_runtime.launch.py \
  planner_backend:=replay \
  model_replay_path:=data/raw/ai/run_01/planner_decisions.jsonl
~~~

Replay requires exactly one matching input fingerprint and version pair. A
missing or ambiguous match fails closed with replay_miss.

## Evidence to retain

Record the endpoint type, model name, planner timeout, vision mode, image size
limit, observation TTL, prompt/output-schema versions, software commit, fixed
task/image set, and the campaign integrity manifest. Planner RuntimeEvent
records the backend, effective backend, model latency, error code, decision
fingerprint, and abstention state without image paths or request bodies.

can_ack_received means command transport delivery only. It is not task success,
docking success, actuator success, or a safety certification result. Use an
application-specific terminal event and held-out experiment protocol to measure
task success.
