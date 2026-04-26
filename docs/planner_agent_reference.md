# Planner Agent Reference

This document records the current Planner Agent implementation after reverting from freeform conceptual planning back to validated, tool-driven planning.

Current intent:

- Planner may reason, but only over grid facts and available backend controls.
- Planner must call tools before final output.
- Planner must use exact backend action type names.
- Planner must validate every action intent before including it in final candidates.
- Simulation remains separate and happens after planning.

## Current Problem This Doc Explains

On `case33bw_data_center_spike_tricky`, the workflow improved the grid but did not clear all violations.

The tools executed correctly:

```text
get_grid_state
get_available_controls
validate_action_intent
simulate_candidate_sequences
```

The planner failure was search depth, not tool failure. It proposed valid short sequences like:

```text
curtail_flexible_load + adjust_reactive_support
dispatch_battery + adjust_reactive_support
increase_local_generation + adjust_reactive_support
shift_data_center_load
```

It did not construct the broader feasible stack:

```text
curtail_flexible_load
shift_data_center_load
dispatch_battery
increase_local_generation
adjust_reactive_support
```

So the issue is planner candidate-construction policy, not missing tool execution.

## Planner Files

Primary planner files:

- `src/gridaware/agents/planner.py`
- `src/gridaware/agents/prompts.py`
- `src/gridaware/agent_tools.py`
- `src/gridaware/tool_executor.py`
- `src/gridaware/agents/responses_runner.py`
- `src/gridaware/agents/models.py`

## Planner Entry Point

File: `src/gridaware/agents/planner.py`

```python
from __future__ import annotations

import json
from typing import Any

from gridaware.agent_tools import responses_tool_definitions
from gridaware.agents.models import AnalyzerReport, PlannerReport, PlannerRunResult
from gridaware.agents.prompts import PLANNER_SYSTEM_PROMPT
from gridaware.agents.responses_runner import (
    DEFAULT_AGENT_MODEL,
    ResponsesClient,
    create_openai_client,
    json_schema_text_format,
    pydantic_strict_json_schema,
    run_responses_agent,
)
from gridaware.tool_executor import GridToolRuntime


def planner_tools() -> list[dict[str, Any]]:
    allowed_names = {"get_grid_state", "get_available_controls", "validate_action_intent"}
    return [tool for tool in responses_tool_definitions() if tool["name"] in allowed_names]


def run_planner_agent(
    runtime: GridToolRuntime,
    analyzer_report: AnalyzerReport,
    *,
    client: ResponsesClient | None = None,
    model: str = DEFAULT_AGENT_MODEL,
) -> PlannerRunResult:
    responses_client = client or create_openai_client()
    result = run_responses_agent(
        client=responses_client,
        model=model,
        system_prompt=PLANNER_SYSTEM_PROMPT,
        user_prompt=_planner_user_prompt(analyzer_report),
        tools=planner_tools(),
        runtime=runtime,
        text_format=json_schema_text_format(
            "planner_report",
            pydantic_strict_json_schema(PlannerReport),
            "Ranked mitigation action sequences for later simulation.",
        ),
        initial_tool_choice={"type": "function", "name": "get_grid_state"},
        max_tool_rounds=24,
    )
    report = PlannerReport.model_validate_json(result.output_text)
    return PlannerRunResult(report=_normalize_planner_report(report), trace=result.trace)


def _planner_user_prompt(analyzer_report: AnalyzerReport) -> str:
    return (
        "Create a mitigation plan from this AnalyzerReport. "
        "Call get_grid_state and get_available_controls before returning the final JSON. "
        "Use validate_action_intent for every action_intent included in final candidates. "
        "Only include action_intents that use allowed action types and backend-shaped fields from "
        "get_available_controls.\n\n"
        f"{json.dumps(analyzer_report.model_dump(mode='json'), indent=2)}"
    )


def _normalize_planner_report(report: PlannerReport) -> PlannerReport:
    candidates = []
    for candidate in report.candidates:
        normalized_sequence = []
        for intent in candidate.action_sequence:
            normalized_sequence.append(_normalize_action_intent(intent))
        candidates.append(candidate.model_copy(update={"action_sequence": normalized_sequence}))
    return report.model_copy(update={"candidates": candidates})


def _normalize_action_intent(intent):
    match intent.type:
        case "shift_data_center_load":
            return intent.model_copy(
                update={
                    "battery_id": None,
                    "generator_id": None,
                    "target_dc": None,
                    "dc": None,
                }
            )
        case "dispatch_battery":
            return intent.model_copy(
                update={
                    "from_dc": None,
                    "to_dc": None,
                    "generator_id": None,
                    "dc": None,
                }
            )
        case "increase_local_generation":
            return intent.model_copy(
                update={
                    "from_dc": None,
                    "to_dc": None,
                    "battery_id": None,
                    "dc": None,
                }
            )
        case "curtail_flexible_load":
            return intent.model_copy(
                update={
                    "from_dc": None,
                    "to_dc": None,
                    "battery_id": None,
                    "generator_id": None,
                    "target_dc": None,
                }
            )
        case "adjust_reactive_support":
            return intent.model_copy(
                update={
                    "from_dc": None,
                    "to_dc": None,
                    "battery_id": None,
                    "generator_id": None,
                    "target_dc": None,
                    "dc": None,
                    "resource_id": intent.resource_id or intent.control_asset,
                    "target_bus": intent.target_bus or intent.target_element,
                    "q_mvar": intent.q_mvar if intent.q_mvar is not None else intent.setpoint,
                    "mw": None,
                }
            )
    return intent
```

## Planner System Prompt

File: `src/gridaware/agents/prompts.py`

```text
You are the Planner Agent for gridAware, a power-grid operations assistant.

Your job is to create ranked mitigation action sequences for later review. You are not allowed to
simulate, evaluate, or apply actions.

Inputs:
- You will receive an AnalyzerReport from the analyzer.
- You must call get_grid_state to inspect current grid facts.
- You must call get_available_controls to inspect scenario-specific allowed action types,
  controllable assets, and action_feasibility_policy.

Required behavior:
- Call get_grid_state before writing the final plan.
- Call get_available_controls before writing the final plan.
- Target active violations before watchlist findings.
- Generate structured action_sequence arrays using only allowed_action_types returned by
  get_available_controls.
- Include both single-step and multi-step sequence candidates when active violations are high or
  critical, when more than one active violation exists, or when one control appears capacity-limited.
- Multi-step sequence candidates should combine complementary controls that target the same active
  violations without duplicating the same exhausted capability.
- For every action in every candidate sequence, call validate_action_intent with the exact
  backend-shaped action intent you plan to include.
- Use normalized_action_intent from validate_action_intent when it is returned.
- Only include actions whose validate_action_intent result is valid.
- For every candidate, include explicit feasibility_checks using the action_feasibility_policy
  returned by get_available_controls.
- Use only valid_checks for the selected action type.
- Do not use checks listed under forbidden_checks.
- Do not mix feasibility checks across action types.
- Every feasibility check must include actual values from get_available_controls or get_grid_state.
- If a required field cannot be supported by available controls, do not propose that action.
- Rank candidates by likely objective fit, feasibility, and operational tradeoff.
- Use watchlist findings as risk constraints, not as primary objectives unless no active violations
  exist.
- Set requires_simulation to true. Planner output is only a proposal.

Forbidden:
- Do not call propose_grid_actions. The planner must reason from grid state and controls, not rank a
  deterministic action menu.
- Do not call simulate_action, simulate_action_sequence, simulate_candidate_sequences,
  evaluate_action_result, apply_action, or compare_grid_states.
- Do not claim an action is safe or successful before simulation.
- Do not invent action types, aliases, grid measurements, assets, or controls.
- Do not include conceptual controls that are not in allowed_action_types.
- Do not include invalid action_intents in final candidates.

Candidate guidance:
- Every candidate must contain an action_sequence list with one or more action_intents.
- For severe active violations, include at least one multi-step action_sequence if two or more
  plausible controls could address the affected asset, zone, corridor, or constraint.
- Use exact backend action type names. For example, use curtail_flexible_load, not adjust_load;
  dispatch_battery, not dispatch_storage; increase_local_generation, not dispatch_generator.
- For adjust_reactive_support, use resource_id, target_bus, and q_mvar. Set mw to null.
- For curtail_flexible_load, use dc and mw. Do not use setpoint as a substitute for mw.
- For dispatch_battery, use battery_id, target_dc, and mw.
- For increase_local_generation, use generator_id, target_dc, and mw.
- For shift_data_center_load, use from_dc, to_dc, and mw.
- For action_intent, set intent_summary to a concise human-readable description.
- Fill applicable structured fields when they fit the action. Use null for fields that do not apply.
- Set validation_passed to true only when every action in the sequence passed validate_action_intent.
- validation_passed_checks should summarize the validate_action_intent passed_checks.
- rejected_options should explain unavailable, invalid, or lower-value options based on grid facts,
  available controls, or validation failures.

Return only JSON matching the requested schema.
```

## Planner User Prompt

The user prompt is generated dynamically from the `AnalyzerReport`.

Code:

```python
def _planner_user_prompt(analyzer_report: AnalyzerReport) -> str:
    return (
        "Create a mitigation plan from this AnalyzerReport. "
        "Call get_grid_state and get_available_controls before returning the final JSON. "
        "Use validate_action_intent for every action_intent included in final candidates. "
        "Only include action_intents that use allowed action types and backend-shaped fields from "
        "get_available_controls.\n\n"
        f"{json.dumps(analyzer_report.model_dump(mode='json'), indent=2)}"
    )
```

So the planner receives:

- Static system prompt.
- Dynamic user prompt containing the analyzer report as JSON.
- Tool definitions for only planner-allowed tools.
- Strict JSON schema requiring `PlannerReport`.

## Planner Output Schema

File: `src/gridaware/agents/models.py`

```python
PlannerConfidence = Literal["low", "medium", "high"]


class PlannerActionIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    intent_summary: str
    from_dc: str | None
    to_dc: str | None
    battery_id: str | None
    generator_id: str | None
    target_dc: str | None
    dc: str | None
    resource_id: str | None
    target_bus: str | None
    q_mvar: float | None
    target_element: str | None
    control_asset: str | None
    setpoint: float | None
    units: str | None
    mw: float | None


class PlannerCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int
    action_sequence: list[PlannerActionIntent]
    validation_passed: bool
    validation_passed_checks: list[str]
    target_violations: list[str]
    feasibility_checks: list[str]
    expected_effect: str
    rationale: str
    risk_notes: list[str]
    planner_confidence: PlannerConfidence


class PlannerReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    planning_summary: str
    primary_objectives: list[str]
    candidates: list[PlannerCandidate]
    rejected_options: list[str]
    requires_simulation: bool


class PlannerRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: PlannerReport
    trace: AgentRunTrace
```

Important detail:

- `PlannerActionIntent.type` is currently `str`, not a strict enum.
- The prompt restricts action types, and validation should enforce backend compatibility.
- This means the schema can technically accept unsupported strings, but the planner should not output them under the current prompt.
- `_normalize_action_intent` cleans irrelevant fields after the LLM output is parsed.

## Planner Tool Set

The global tool registry lives in `src/gridaware/agent_tools.py`.

Planner exposes only:

```python
allowed_names = {"get_grid_state", "get_available_controls", "validate_action_intent"}
```

The planner cannot call:

- `propose_grid_actions`
- `simulate_action`
- `simulate_action_sequence`
- `simulate_candidate_sequences`
- `evaluate_action_result`
- `apply_action`
- `compare_grid_states`

## Tool 1: get_grid_state

### Tool Definition

From `responses_tool_definitions()`:

```python
{
    "type": "function",
    "name": "get_grid_state",
    "description": (
        "Inspect the active grid scenario, including violations, bus voltages, "
        "line loading, assets, data center loads, and grid health score."
    ),
    "parameters": _empty_parameters(),
    "strict": True,
}
```

### Parameters

```json
{
  "type": "object",
  "properties": {},
  "required": [],
  "additionalProperties": false
}
```

### Runtime Execution

File: `src/gridaware/tool_executor.py`

```python
def get_grid_state(self) -> dict[str, Any]:
    return {"ok": True, "grid_state": get_grid_state(self.active_state).model_dump(mode="json")}
```

### What It Returns

It returns the current active `GridState`:

- `scenario_id`
- `metadata`
- `bus_voltages`
- `line_loadings`
- `data_centers`
- `batteries`
- `local_generators`
- `reactive_resources`
- `violations`
- `grid_health_score`

### Planner Usage

The planner uses it to inspect actual current violations and asset values.

Example facts from `case33bw_data_center_spike_tricky`:

```text
line_25 = 147.4%
DC_A voltage = 0.904 pu
DC_A flexible_mw = 0.30
BAT_A available_mw = 0.20
GEN_A available_headroom_mw = 0.20
VAR_A available_mvar = 0.20
DC_B receiving_headroom_mw = 0.15
```

## Tool 2: get_available_controls

### Tool Definition

```python
{
    "type": "function",
    "name": "get_available_controls",
    "description": (
        "Return the allowed mitigation action types and controllable grid assets, including "
        "data center flexibility, receiving headroom, batteries, local generation, and "
        "reactive support."
    ),
    "parameters": _empty_parameters(),
    "strict": True,
}
```

### Parameters

```json
{
  "type": "object",
  "properties": {},
  "required": [],
  "additionalProperties": false
}
```

### Runtime Execution

File: `src/gridaware/tool_executor.py`

```python
def get_available_controls(self) -> dict[str, Any]:
    allowed_action_types = (
        self.scenario_bundle.allowed_action_types
        if self.scenario_bundle is not None
        else [
            "shift_data_center_load",
            "dispatch_battery",
            "increase_local_generation",
            "curtail_flexible_load",
        ]
    )
    return {
        "ok": True,
        "allowed_action_types": allowed_action_types,
        "data_centers": [
            {
                "id": dc.id,
                "zone": dc.zone,
                "load_mw": dc.load_mw,
                "flexible_mw": dc.flexible_mw,
                "max_load_mw": dc.max_load_mw,
                "receiving_headroom_mw": round(dc.max_load_mw - dc.load_mw, 3),
            }
            for dc in self.active_state.data_centers
        ],
        "batteries": [
            battery.model_dump(mode="json") for battery in self.active_state.batteries
        ],
        "local_generators": [
            generator.model_dump(mode="json")
            for generator in self.active_state.local_generators
        ],
        "reactive_resources": [
            resource.model_dump(mode="json")
            for resource in self.active_state.reactive_resources
        ],
        "control_assets": {
            "data_centers": [
                {
                    "id": dc.id,
                    "zone": dc.zone,
                    "load_mw": dc.load_mw,
                    "flexible_mw": dc.flexible_mw,
                    "max_load_mw": dc.max_load_mw,
                    "receiving_headroom_mw": round(dc.max_load_mw - dc.load_mw, 3),
                }
                for dc in self.active_state.data_centers
            ],
            "batteries": [
                battery.model_dump(mode="json") for battery in self.active_state.batteries
            ],
            "local_generators": [
                generator.model_dump(mode="json")
                for generator in self.active_state.local_generators
            ],
            "reactive_resources": [
                resource.model_dump(mode="json")
                for resource in self.active_state.reactive_resources
            ],
            "capacitor_banks": [],
            "transformers": [],
            "switches": [],
        },
        "action_feasibility_policy": _action_feasibility_policy(),
    }
```

### What It Returns

For data-center scenarios, allowed actions are:

```json
[
  "shift_data_center_load",
  "dispatch_battery",
  "increase_local_generation",
  "curtail_flexible_load",
  "adjust_reactive_support"
]
```

It also returns:

- data centers and receiving headroom
- batteries
- local generators
- reactive resources
- `control_assets` grouped by asset class
- `action_feasibility_policy`

### Action Feasibility Policy

Runtime policy:

```python
def _action_feasibility_policy() -> dict[str, Any]:
    return {
        "shift_data_center_load": {
            "required_fields": ["from_dc", "to_dc", "mw"],
            "valid_checks": [
                "from_dc exists in data_centers",
                "to_dc exists in data_centers",
                "from_dc != to_dc",
                "mw <= from_dc.flexible_mw",
                "mw <= to_dc.receiving_headroom_mw",
            ],
        },
        "dispatch_battery": {
            "required_fields": ["battery_id", "target_dc", "mw"],
            "valid_checks": [
                "battery_id exists in batteries",
                "target_dc exists in data_centers",
                "mw <= battery.available_mw",
                "battery.zone should match target_dc.zone or support the target zone",
            ],
            "forbidden_checks": [
                "target_dc.receiving_headroom_mw",
                "target_dc.flexible_mw",
            ],
        },
        "increase_local_generation": {
            "required_fields": ["generator_id", "target_dc", "mw"],
            "valid_checks": [
                "generator_id exists in local_generators",
                "target_dc exists in data_centers",
                "mw <= generator.available_headroom_mw",
                "generator.zone should match target_dc.zone or support the target zone",
            ],
            "forbidden_checks": [
                "target_dc.receiving_headroom_mw",
                "target_dc.flexible_mw",
            ],
        },
        "curtail_flexible_load": {
            "required_fields": ["dc", "mw"],
            "valid_checks": [
                "dc exists in data_centers",
                "mw <= dc.flexible_mw",
            ],
            "forbidden_checks": [
                "receiving_headroom_mw",
                "battery.available_mw",
                "generator.available_headroom_mw",
            ],
        },
        "adjust_reactive_support": {
            "required_fields": ["resource_id", "target_bus", "q_mvar"],
            "valid_checks": [
                "resource_id exists in reactive_resources",
                "target_bus exists in bus_voltages",
                "q_mvar <= resource.available_mvar",
                "resource.zone should match target_bus zone or support the target zone",
            ],
            "forbidden_checks": [
                "mw",
                "target_dc.receiving_headroom_mw",
                "battery.available_mw",
                "generator.available_headroom_mw",
            ],
        },
    }
```

### Planner Usage

The planner should use this tool to:

- know which action types are legal
- know which assets exist
- know numeric limits for each asset
- know required fields per action type
- know which checks are valid or forbidden

## Tool 3: validate_action_intent

### Tool Definition

```python
{
    "type": "function",
    "name": "validate_action_intent",
    "description": (
        "Run deterministic backend feasibility checks for a drafted mitigation action "
        "intent. Use this before including any action_intent in the final planner report."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action_intent": {
                **_action_intent_schema(),
                "description": "Structured mitigation action intent to validate.",
            }
        },
        "required": ["action_intent"],
        "additionalProperties": False,
    },
    "strict": True,
}
```

### Action Intent Schema

```python
ACTION_TYPE_ENUM = [
    "shift_data_center_load",
    "dispatch_battery",
    "increase_local_generation",
    "curtail_flexible_load",
    "adjust_reactive_support",
]
```

```python
def _action_intent_schema() -> dict[str, Any]:
    nullable_string = {
        "type": ["string", "null"],
        "description": "Required for some action types; use null when not applicable.",
    }
    return {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ACTION_TYPE_ENUM,
                "description": "Allowed mitigation action type.",
            },
            "from_dc": nullable_string,
            "to_dc": nullable_string,
            "battery_id": nullable_string,
            "generator_id": nullable_string,
            "target_dc": nullable_string,
            "dc": nullable_string,
            "resource_id": nullable_string,
            "target_bus": nullable_string,
            "q_mvar": {
                "type": ["number", "null"],
                "description": "Reactive power in MVAr for voltage-support actions.",
            },
            "mw": {
                "type": ["number", "null"],
                "description": "Megawatts to shift, dispatch, generate, or curtail.",
            },
        },
        "required": [
            "type",
            "from_dc",
            "to_dc",
            "battery_id",
            "generator_id",
            "target_dc",
            "dc",
            "resource_id",
            "target_bus",
            "q_mvar",
            "mw",
        ],
        "additionalProperties": False,
    }
```

### Runtime Execution

File: `src/gridaware/tool_executor.py`

```python
def validate_action_intent(self, action_intent: dict[str, Any]) -> dict[str, Any]:
    validation = validate_action_intent_for_planner(
        self.active_state,
        ActionIntent.model_validate(action_intent),
    )
    return {"ok": True, "validation": validation.model_dump(mode="json")}
```

This calls:

```python
validate_action_intent_for_planner(self.active_state, ActionIntent.model_validate(action_intent))
```

So validation happens against the current active grid state and the strict backend `ActionIntent` model.

### Validation Output Shape

From `src/gridaware/models.py`:

```python
class ActionIntentValidation(BaseModel):
    valid: bool
    action_intent: ActionIntent
    normalized_action_intent: ActionIntent | None = None
    passed_checks: list[str]
    failed_checks: list[str]
    repair_guidance: list[str]
```

Planner should:

- include action only when `valid == true`
- prefer `normalized_action_intent` when present
- copy useful `passed_checks` into `validation_passed_checks`
- reject or repair actions when `failed_checks` is non-empty

## Responses API Execution Loop

File: `src/gridaware/agents/responses_runner.py`

```python
def run_responses_agent(
    *,
    client: ResponsesClient,
    model: str,
    system_prompt: str,
    user_prompt: str,
    tools: list[dict[str, Any]],
    runtime: GridToolRuntime,
    text_format: dict[str, Any],
    max_tool_rounds: int = 4,
    initial_tool_choice: dict[str, Any] | None = None,
) -> ResponsesRunResult:
    allowed_tool_names = {tool["name"] for tool in tools}
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        tools=tools,
        text={"format": text_format},
        parallel_tool_calls=False,
        tool_choice=initial_tool_choice,
    )
    trace = AgentRunTrace(response_ids=[response.id])

    for _ in range(max_tool_rounds):
        function_calls = _function_calls(response)
        if not function_calls:
            return ResponsesRunResult(output_text=response.output_text, trace=trace)

        tool_outputs = []
        for call in function_calls:
            if call.name not in allowed_tool_names:
                raise RuntimeError(f"Agent requested disallowed tool: {call.name}")
            output = runtime.execute(call.name, call.arguments)
            trace.tool_calls.append(
                AgentToolCallTrace(name=call.name, arguments=call.arguments, output=output)
            )
            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": output,
                }
            )

        response = client.responses.create(
            model=model,
            previous_response_id=response.id,
            input=tool_outputs,
            tools=tools,
            text={"format": text_format},
            parallel_tool_calls=False,
            tool_choice="auto",
        )
        trace.response_ids.append(response.id)

    raise RuntimeError(f"Agent exceeded max_tool_rounds={max_tool_rounds}")
```

Execution details:

- First call sends system prompt, user prompt, tools, strict text format, and initial tool choice.
- Planner initial tool choice is forced to `get_grid_state`.
- `parallel_tool_calls=False`, so tool execution is serialized.
- Tool calls are only accepted if the tool name is in `allowed_tool_names`.
- Runtime executes tool calls through `GridToolRuntime.execute`.
- Tool output is returned to Responses API using `function_call_output`.
- Follow-up calls use `tool_choice="auto"`.
- Planner has `max_tool_rounds=24`.
- If no tool calls are returned, final `response.output_text` is parsed as `PlannerReport`.

## Tool Runtime Dispatcher

File: `src/gridaware/tool_executor.py`

```python
def execute(self, name: str, arguments: dict[str, Any] | str | None) -> str:
    args = _normalize_arguments(arguments)
    try:
        match name:
            case "get_grid_state":
                payload = self.get_grid_state()
            case "propose_grid_actions":
                payload = self.propose_grid_actions(args["target_violation_id"])
            case "get_available_controls":
                payload = self.get_available_controls()
            case "validate_action_intent":
                payload = self.validate_action_intent(args["action_intent"])
            case "simulate_action":
                payload = self.simulate_action(args["action_id"], args["action_intent"])
            case "simulate_action_intent":
                payload = self.simulate_action_intent(args["action_intent"])
            case "simulate_action_sequence":
                payload = self.simulate_action_sequence(args["action_intents"])
            case "simulate_candidate_sequences":
                payload = self.simulate_candidate_sequences(args["candidates"])
            case "evaluate_action_result":
                payload = self.evaluate_action_result(args["action_id"])
            case "apply_action":
                payload = self.apply_action(args["action_id"])
            case "compare_grid_states":
                payload = self.compare_grid_states()
            case _:
                return _json_error(f"Unknown tool: {name}")
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        return _json_error(str(exc))

    return json.dumps(payload, separators=(",", ":"))
```

Important details:

- Arguments may arrive as a JSON string or dict.
- `_normalize_arguments` parses string arguments with `json.loads`.
- Tool errors are returned as JSON:

```json
{"ok": false, "error": "..."}
```

- Successful outputs are compact JSON strings.

## Full Planner Workflow

Current sequence:

```text
AnalyzerReport
  -> run_planner_agent(runtime, analyzer_report)
  -> create OpenAI client if not provided
  -> call run_responses_agent
  -> first Responses call forced to get_grid_state
  -> runtime.execute("get_grid_state")
  -> model receives grid state
  -> model should call get_available_controls
  -> runtime.execute("get_available_controls")
  -> model receives allowed action types, assets, feasibility policy
  -> model drafts action_intents
  -> model calls validate_action_intent once per action intent
  -> runtime validates each action against current GridState
  -> model receives valid/invalid checks
  -> model returns PlannerReport JSON
  -> code parses PlannerReport
  -> _normalize_planner_report cleans irrelevant fields
  -> PlannerRunResult returned with report + tool trace
```

## What The Planner Actually Did In Last Tricky Run

Log:

```text
runs/full_workflow_validated_planner_case33bw_data_center_spike_tricky_1777171267.json
```

Planner tool calls:

```text
get_grid_state
get_available_controls
validate_action_intent
validate_action_intent
validate_action_intent
validate_action_intent
```

Planner produced 4 valid candidates:

1. `curtail_flexible_load 0.3 MW` + `adjust_reactive_support 0.2 MVAr`
2. `dispatch_battery 0.2 MW` + `adjust_reactive_support 0.2 MVAr`
3. `increase_local_generation 0.2 MW` + `adjust_reactive_support 0.2 MVAr`
4. `shift_data_center_load 0.1 MW`

Simulator result:

```text
best candidate rank: 1
line_25: 147.4% -> 116.4%
DC_A voltage: 0.904 pu -> 0.931 pu
grid health: 0 -> 27
remaining violations: line_25 overload, DC_A low voltage
```

## Why It Did Not Solve The Tricky Scenario

The planner used tools correctly, but its candidate search was shallow.

It validated individual or paired candidates, but did not compose a max-feasible stack.

It should have considered a candidate like:

```json
{
  "rank": 1,
  "action_sequence": [
    {
      "type": "curtail_flexible_load",
      "dc": "DC_A",
      "mw": 0.15
    },
    {
      "type": "shift_data_center_load",
      "from_dc": "DC_A",
      "to_dc": "DC_B",
      "mw": 0.15
    },
    {
      "type": "dispatch_battery",
      "battery_id": "BAT_A",
      "target_dc": "DC_A",
      "mw": 0.20
    },
    {
      "type": "increase_local_generation",
      "generator_id": "GEN_A",
      "target_dc": "DC_A",
      "mw": 0.20
    },
    {
      "type": "adjust_reactive_support",
      "resource_id": "VAR_A",
      "target_bus": "DC_A",
      "q_mvar": 0.20
    }
  ]
}
```

That candidate is broader than what the planner tried. It uses all non-conflicting available controls:

- DC_A curtailment
- DC_A to DC_B load shift within receiving headroom
- battery support
- generation support
- reactive support

Current prompt asks for multi-step sequences, but does not force a max-feasible composite candidate.

## What We Should Change Next

No new planner tools are required for this specific failure.

The missing behavior is a planner search rule:

```text
When active violations are severe and individual controls are capacity-limited, include at least one
max-feasible composite candidate that stacks every validated, non-conflicting local control relevant
to the violations.
```

Recommended prompt addition:

```text
Candidate construction requirements:
- Always produce at least four candidates when two or more active violations exist:
  1. best minimal candidate
  2. thermal-first candidate
  3. voltage-first candidate
  4. max-feasible composite candidate
- The max-feasible composite candidate must include every validated, non-conflicting control that
  targets the active violations.
- For data-center overload plus low-voltage cases, test whether these controls are available:
  curtail_flexible_load, shift_data_center_load, dispatch_battery,
  increase_local_generation, adjust_reactive_support.
- If available and valid, include them in the max-feasible composite candidate unless there is a
  clear conflict.
- Validate every action in the composite candidate before final output.
```

This keeps the same tools and same backend validation while making planner search deeper and less dependent on intuition.

## Current Boundary

Planner does not simulate.

Planner does not know whether a candidate will fully fix the grid. It can only reason from:

- current grid facts
- available controls
- deterministic validation results

The simulator later determines actual electrical impact using pandapower:

```text
PlannerReport
  -> Simulator Agent
  -> simulate_candidate_sequences
  -> pandapower runpp after each cumulative step
  -> final SimulationReport
```

Therefore, the planner should produce diverse and sufficiently broad candidates, not try to perfectly predict the physics.
