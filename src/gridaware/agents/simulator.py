from __future__ import annotations

import json
from typing import Any

from gridaware.agent_tools import responses_tool_definitions
from gridaware.agents.models import (
    AgentRunTrace,
    FinalGridStateSummary,
    PlannerActionIntent,
    PlannerCandidate,
    PlannerReport,
    SimulatedActionResult,
    SimulatorReport,
    SimulatorRunResult,
)
from gridaware.agents.prompts import SIMULATOR_SYSTEM_PROMPT
from gridaware.agents.responses_runner import (
    DEFAULT_AGENT_MODEL,
    ResponsesClient,
    create_openai_client,
    json_schema_text_format,
    pydantic_strict_json_schema,
    run_responses_agent,
)
from gridaware.models import GridState
from gridaware.tool_executor import GridToolRuntime


def simulator_tools() -> list[dict[str, Any]]:
    return [
        tool
        for tool in responses_tool_definitions()
        if tool["name"] == "simulate_candidate_sequences"
    ]


def run_simulator_agent(
    runtime: GridToolRuntime,
    planner_report: PlannerReport,
    *,
    client: ResponsesClient | None = None,
    model: str = DEFAULT_AGENT_MODEL,
) -> SimulatorRunResult:
    responses_client = client or create_openai_client()
    result = run_responses_agent(
        client=responses_client,
        model=model,
        system_prompt=SIMULATOR_SYSTEM_PROMPT,
        user_prompt=_simulator_user_prompt(planner_report, runtime.active_state),
        tools=simulator_tools(),
        runtime=runtime,
        text_format=json_schema_text_format(
            "simulator_report",
            pydantic_strict_json_schema(SimulatorReport),
            "Simulation report comparing before and after grid states for planner candidates.",
        ),
        initial_tool_choice={"type": "function", "name": "simulate_candidate_sequences"},
        max_tool_rounds=4,
    )
    report = SimulatorReport.model_validate_json(result.output_text)
    return SimulatorRunResult(
        report=_normalize_simulator_report(report, result.trace),
        trace=result.trace,
    )


def _simulator_user_prompt(planner_report: PlannerReport, grid_state: GridState) -> str:
    simulation_candidates, unsupported_candidates = _simulation_candidates(
        planner_report, grid_state
    )
    return (
        "Simulate every candidate in this PlannerReport. "
        "Call simulate_candidate_sequences exactly once using the exact simulation_candidates "
        "payload below as the tool arguments. "
        "Do not simulate only the top-ranked candidate unless this PlannerReport contains only one "
        "candidate. Do not return final JSON until every candidate has a simulation result or "
        "validation failure. If unsupported_candidates is not empty, report those candidates as "
        "failed because they could not be translated to executable backend action_intents.\n\n"
        "Tool arguments for simulate_candidate_sequences:\n"
        f"{json.dumps({'candidates': simulation_candidates}, indent=2)}\n\n"
        "Unsupported candidates:\n"
        f"{json.dumps(unsupported_candidates, indent=2)}\n\n"
        "Original PlannerReport for explanation context only. Do not use this object as tool "
        "arguments:\n"
        f"{json.dumps(planner_report.model_dump(mode='json'), indent=2)}"
    )


def _simulation_candidates(
    planner_report: PlannerReport,
    grid_state: GridState | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    simulation_candidates: list[dict[str, Any]] = []
    unsupported_candidates: list[dict[str, Any]] = []

    for candidate in planner_report.candidates:
        action_intents: list[dict[str, Any]] = []
        unsupported_reasons: list[str] = []
        for intent in candidate.action_sequence:
            translated = _to_backend_action_intent(intent, grid_state)
            if translated is None:
                unsupported_reasons.append(
                    f"{intent.type}: no executable backend mapping for this planner action"
                )
            else:
                action_intents.append(translated)

        if unsupported_reasons:
            unsupported_candidates.append(
                {
                    "candidate_id": _candidate_id(candidate),
                    "rank": candidate.rank,
                    "unsupported_reasons": unsupported_reasons,
                }
            )
            continue

        simulation_candidates.append(
            {
                "candidate_id": _candidate_id(candidate),
                "rank": candidate.rank,
                "action_intents": action_intents,
            }
        )

    return simulation_candidates, unsupported_candidates


def _to_backend_action_intent(
    intent: PlannerActionIntent, grid_state: GridState | None = None
) -> dict[str, Any] | None:
    action_type = _backend_action_type(intent.type)
    target_dc = _target_dc(intent)

    match action_type:
        case "shift_data_center_load":
            if not intent.from_dc or not intent.to_dc or intent.mw is None:
                return None
            return _action_payload(
                action_type,
                from_dc=intent.from_dc,
                to_dc=intent.to_dc,
                mw=intent.mw,
            )
        case "dispatch_battery":
            battery_id = intent.battery_id or _asset_id(intent)
            if not battery_id or not target_dc or intent.mw is None:
                return None
            return _action_payload(
                action_type,
                battery_id=battery_id,
                target_dc=target_dc,
                mw=intent.mw,
            )
        case "increase_local_generation":
            generator_id = intent.generator_id or _asset_id(intent)
            if not generator_id or not target_dc or intent.mw is None:
                return None
            return _action_payload(
                action_type,
                generator_id=generator_id,
                target_dc=target_dc,
                mw=intent.mw,
            )
        case "curtail_flexible_load":
            dc = intent.dc or target_dc
            mw = _curtail_mw(intent, grid_state, dc)
            if not dc or mw is None:
                return None
            return _action_payload(action_type, dc=dc, mw=mw)
        case "adjust_reactive_support":
            resource_id = intent.resource_id or _asset_id(intent)
            target_bus = intent.target_bus or intent.target_element or target_dc
            if not resource_id or not target_bus or intent.q_mvar is None:
                return None
            return _action_payload(
                action_type,
                resource_id=resource_id,
                target_bus=target_bus,
                q_mvar=intent.q_mvar,
            )
    return None


def _backend_action_type(action_type: str) -> str | None:
    aliases = {
        "shift_data_center_load": "shift_data_center_load",
        "shift_load": "shift_data_center_load",
        "load_shift": "shift_data_center_load",
        "dispatch_battery": "dispatch_battery",
        "battery_dispatch": "dispatch_battery",
        "dispatch_storage": "dispatch_battery",
        "adjust_storage": "dispatch_battery",
        "adjust_storage_discharge": "dispatch_battery",
        "adjust_battery_dispatch": "dispatch_battery",
        "storage_discharge": "dispatch_battery",
        "discharge_battery": "dispatch_battery",
        "increase_local_generation": "increase_local_generation",
        "adjust_generation": "increase_local_generation",
        "adjust_local_generation": "increase_local_generation",
        "dispatch_generation": "increase_local_generation",
        "dispatch_generator": "increase_local_generation",
        "dispatch_local_generation": "increase_local_generation",
        "curtail_flexible_load": "curtail_flexible_load",
        "adjust_load": "curtail_flexible_load",
        "curtail_load": "curtail_flexible_load",
        "load_curtailment": "curtail_flexible_load",
        "adjust_reactive_support": "adjust_reactive_support",
        "reactive_support": "adjust_reactive_support",
        "inject_reactive_power": "adjust_reactive_support",
    }
    return aliases.get(action_type)


def _action_payload(action_type: str, **updates: Any) -> dict[str, Any]:
    payload = {
        "type": action_type,
        "from_dc": None,
        "to_dc": None,
        "battery_id": None,
        "generator_id": None,
        "target_dc": None,
        "dc": None,
        "resource_id": None,
        "target_bus": None,
        "q_mvar": None,
        "mw": None,
    }
    payload.update(updates)
    return payload


def _target_dc(intent: PlannerActionIntent) -> str | None:
    for value in (intent.target_dc, intent.dc, intent.target_bus, intent.target_element):
        if value and value.startswith("DC_"):
            return value
    return None


def _asset_id(intent: PlannerActionIntent) -> str | None:
    return intent.control_asset or intent.resource_id


def _curtail_mw(
    intent: PlannerActionIntent, grid_state: GridState | None, dc_id: str | None
) -> float | None:
    if intent.mw is not None:
        return intent.mw
    if intent.setpoint is None or grid_state is None or dc_id is None:
        return None
    data_center = next((item for item in grid_state.data_centers if item.id == dc_id), None)
    if data_center is None:
        return None
    reduction = round(data_center.load_mw - intent.setpoint, 6)
    return reduction if reduction > 0 else None


def _candidate_id(candidate: PlannerCandidate) -> str:
    return f"candidate_{candidate.rank}"


def _normalize_simulator_report(
    report: SimulatorReport,
    trace: AgentRunTrace,
) -> SimulatorReport:
    raw_results = _raw_simulation_results(trace)
    if not raw_results:
        return report

    raw_by_rank = {item["rank"]: item["result"] for item in raw_results}
    action_results = [
        _normalize_action_result(action_result, raw_by_rank.get(action_result.candidate_rank))
        for action_result in report.action_results
    ]
    existing_ranks = {action_result.candidate_rank for action_result in action_results}
    for raw in raw_results:
        if raw["rank"] not in existing_ranks:
            action_results.append(_action_result_from_raw(raw["rank"], raw["result"]))

    best_rank = _best_candidate_rank(raw_results)
    best_result = next(
        (item["result"] for item in raw_results if item["rank"] == best_rank),
        None,
    )
    final_state = _final_grid_state(best_result) if best_result else None
    return report.model_copy(
        update={
            "simulation_summary": _simulation_summary(raw_results, best_rank),
            "action_results": sorted(action_results, key=lambda item: item.candidate_rank),
            "best_candidate_rank": best_rank,
            "final_grid_status": _final_grid_status(final_state),
            "final_grid_state": final_state,
        }
    )


def _raw_simulation_results(trace: AgentRunTrace) -> list[dict[str, Any]]:
    for call in trace.tool_calls:
        if call.name != "simulate_candidate_sequences":
            continue
        try:
            payload = json.loads(call.output)
        except json.JSONDecodeError:
            return []
        results = payload.get("candidate_results", [])
        return results if isinstance(results, list) else []
    return []


def _normalize_action_result(
    action_result: SimulatedActionResult,
    raw_result: dict[str, Any] | None,
) -> SimulatedActionResult:
    if raw_result is None:
        return action_result
    raw_action_result = _action_result_from_raw(action_result.candidate_rank, raw_result)
    return action_result.model_copy(
        update={
            "sequence_completed": raw_action_result.sequence_completed,
            "failed_step_index": raw_action_result.failed_step_index,
            "power_flow_converged": raw_action_result.power_flow_converged,
            "successful_changes": raw_action_result.successful_changes,
            "failed_changes": raw_action_result.failed_changes,
            "grid_changes_summary": raw_action_result.grid_changes_summary,
            "remaining_violations": raw_action_result.remaining_violations,
            "final_grid_health_score": raw_action_result.final_grid_health_score,
        }
    )


def _action_result_from_raw(rank: int, raw_result: dict[str, Any]) -> SimulatedActionResult:
    final_state = raw_result.get("final_state") or {}
    final_diff = raw_result.get("final_diff") or {}
    remaining = _violation_labels(final_state.get("violations", []))
    return SimulatedActionResult(
        candidate_rank=rank,
        action_sequence=[
            PlannerActionIntent(
                intent_summary=f"Simulated {intent['type']}.",
                target_element=None,
                control_asset=None,
                setpoint=None,
                units=None,
                **intent,
            )
            for intent in raw_result.get("action_intents", [])
        ],
        sequence_completed=bool(raw_result.get("sequence_completed")),
        failed_step_index=raw_result.get("failed_step_index"),
        power_flow_converged=_power_flow_converged(raw_result),
        successful_changes=_successful_changes(final_diff, final_state),
        failed_changes=_failed_changes(remaining, raw_result),
        grid_changes_summary=_grid_changes_summary(rank, final_state, remaining),
        remaining_violations=remaining,
        final_grid_health_score=final_state.get("grid_health_score"),
    )


def _best_candidate_rank(raw_results: list[dict[str, Any]]) -> int | None:
    if not raw_results:
        return None

    def score(item: dict[str, Any]) -> tuple[int, int, float]:
        result = item["result"]
        final_state = result.get("final_state") or {}
        remaining_count = len(final_state.get("violations", []))
        completed = 1 if result.get("sequence_completed") else 0
        health = float(final_state.get("grid_health_score") or 0)
        return (completed, -remaining_count, health)

    return max(raw_results, key=score)["rank"]


def _final_grid_state(raw_result: dict[str, Any] | None) -> FinalGridStateSummary | None:
    if raw_result is None:
        return None
    final_state = raw_result.get("final_state")
    if not final_state:
        return None
    return FinalGridStateSummary(
        scenario_id=final_state["scenario_id"],
        grid_health_score=final_state["grid_health_score"],
        remaining_violations=_violation_labels(final_state.get("violations", [])),
        max_line_loading_percent=max(
            (line["loading_percent"] for line in final_state.get("line_loadings", [])),
            default=0.0,
        ),
        min_bus_voltage_pu=min(
            (bus["vm_pu"] for bus in final_state.get("bus_voltages", [])),
            default=1.0,
        ),
    )


def _simulation_summary(raw_results: list[dict[str, Any]], best_rank: int | None) -> str:
    completed = sum(1 for item in raw_results if item["result"].get("sequence_completed"))
    cleared = sum(
        1
        for item in raw_results
        if item["result"].get("final_state")
        and not item["result"]["final_state"].get("violations", [])
    )
    return (
        f"Simulated {len(raw_results)} candidates from the same baseline; {completed} completed "
        f"and {cleared} cleared all violations. Best candidate rank: {best_rank}."
    )


def _final_grid_status(final_state: FinalGridStateSummary | None) -> str:
    if final_state is None:
        return "No completed simulation result was available."
    if final_state.remaining_violations:
        return (
            "Improved or evaluated, but remaining violations persist: "
            f"{', '.join(final_state.remaining_violations)}."
        )
    return "Healthy after mitigation; selected candidate has no remaining violations."


def _successful_changes(final_diff: dict[str, Any], final_state: dict[str, Any]) -> list[str]:
    changes: list[str] = []
    score_change = final_diff.get("score_change", {})
    if score_change:
        changes.append(
            "Grid health score changed from "
            f"{score_change.get('before')} to {score_change.get('after')}."
        )
    resolved = _violation_labels(final_diff.get("resolved_violations", []))
    if resolved:
        changes.append(f"Resolved violations: {', '.join(resolved)}.")
    if final_state:
        max_line = max(
            (line["loading_percent"] for line in final_state.get("line_loadings", [])),
            default=0.0,
        )
        min_voltage = min(
            (bus["vm_pu"] for bus in final_state.get("bus_voltages", [])),
            default=1.0,
        )
        changes.append(f"Final max line loading is {max_line:g}%.")
        changes.append(f"Final minimum bus voltage is {min_voltage:g} pu.")
    return changes


def _failed_changes(remaining: list[str], raw_result: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if not raw_result.get("sequence_completed"):
        failures.append(raw_result.get("error") or "Sequence did not complete.")
    if remaining:
        failures.append(f"Remaining violations: {', '.join(remaining)}.")
    return failures


def _grid_changes_summary(
    rank: int,
    final_state: dict[str, Any],
    remaining: list[str],
) -> str:
    if not final_state:
        return f"Candidate {rank} did not produce a final grid state."
    if remaining:
        return f"Candidate {rank} completed with remaining violations: {', '.join(remaining)}."
    return f"Candidate {rank} completed with no remaining violations."


def _power_flow_converged(raw_result: dict[str, Any]) -> bool:
    steps = raw_result.get("step_results", [])
    return bool(steps) and all(step.get("power_flow_converged") for step in steps)


def _violation_labels(violations: list[dict[str, Any]]) -> list[str]:
    labels = []
    for violation in violations:
        violation_type = violation.get("type", "violation")
        element_id = violation.get("element_id", "unknown")
        if "observed" in violation:
            labels.append(
                f"{violation_type} {element_id} at "
                f"{violation['observed']:g}{_unit_suffix(violation)}"
            )
        else:
            labels.append(f"{violation_type} {element_id}")
    return labels


def _unit_suffix(violation: dict[str, Any]) -> str:
    units = violation.get("units")
    if units == "percent":
        return "%"
    if units:
        return f" {units}"
    return ""
