from __future__ import annotations

import json
from typing import Any

from gridaware.agent_tools import responses_tool_definitions
from gridaware.agents.models import (
    PlannerActionIntent,
    PlannerCandidate,
    PlannerReport,
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
    return SimulatorRunResult(
        report=SimulatorReport.model_validate_json(result.output_text),
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
        "storage_discharge": "dispatch_battery",
        "discharge_battery": "dispatch_battery",
        "increase_local_generation": "increase_local_generation",
        "adjust_generation": "increase_local_generation",
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
