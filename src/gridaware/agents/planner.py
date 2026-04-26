from __future__ import annotations

import json
from typing import Any

from gridaware.agent_tools import responses_tool_definitions
from gridaware.agents.models import (
    AgentRunTrace,
    AnalyzerReport,
    PlannerReport,
    PlannerRunResult,
)
from gridaware.agents.prompts import PLANNER_SYSTEM_PROMPT
from gridaware.agents.responses_runner import (
    DEFAULT_AGENT_MODEL,
    ResponsesClient,
    create_openai_client,
    json_schema_text_format,
    pydantic_strict_json_schema,
    run_responses_agent,
)
from gridaware.planner_coverage import PlannerCoverageResult, check_planner_coverage
from gridaware.tool_executor import GridToolRuntime


def planner_tools() -> list[dict[str, Any]]:
    allowed_names = {
        "get_grid_state",
        "get_available_controls",
        "build_candidate_archetypes",
        "validate_action_intent",
    }
    return [tool for tool in responses_tool_definitions() if tool["name"] in allowed_names]


def run_planner_agent(
    runtime: GridToolRuntime,
    analyzer_report: AnalyzerReport,
    *,
    client: ResponsesClient | None = None,
    model: str = DEFAULT_AGENT_MODEL,
) -> PlannerRunResult:
    responses_client = client or create_openai_client()
    result = _run_planner_once(
        responses_client,
        model,
        runtime,
        _planner_user_prompt(analyzer_report),
    )
    report = _normalize_planner_report(PlannerReport.model_validate_json(result.output_text))
    coverage = check_planner_coverage(
        report, runtime.active_state, runtime.get_available_controls()
    )
    if coverage.passed:
        return PlannerRunResult(report=report, trace=result.trace)

    repair_result = _run_planner_once(
        responses_client,
        model,
        runtime,
        _planner_repair_prompt(analyzer_report, report, coverage),
    )
    repaired_report = _normalize_planner_report(
        PlannerReport.model_validate_json(repair_result.output_text)
    )
    repaired_coverage = check_planner_coverage(
        repaired_report, runtime.active_state, runtime.get_available_controls()
    )
    trace = _merge_traces(result.trace, repair_result.trace)
    if not repaired_coverage.passed:
        issue_text = "; ".join(issue.message for issue in repaired_coverage.issues)
        raise RuntimeError(f"Planner coverage failed after repair: {issue_text}")
    return PlannerRunResult(report=repaired_report, trace=trace)


def _run_planner_once(
    responses_client: ResponsesClient,
    model: str,
    runtime: GridToolRuntime,
    user_prompt: str,
):
    result = run_responses_agent(
        client=responses_client,
        model=model,
        system_prompt=PLANNER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        tools=planner_tools(),
        runtime=runtime,
        text_format=json_schema_text_format(
            "planner_report",
            pydantic_strict_json_schema(PlannerReport),
            "Ranked mitigation action sequences for later simulation.",
        ),
        initial_tool_choice={"type": "function", "name": "get_grid_state"},
        max_tool_rounds=32,
    )
    return result


def _planner_user_prompt(analyzer_report: AnalyzerReport) -> str:
    return (
        "Create a mitigation plan from this AnalyzerReport. "
        "Call get_grid_state, get_available_controls, and build_candidate_archetypes before "
        "returning the final JSON. "
        "Use validate_action_intent for every action_intent included in final candidates. "
        "Only include action_intents that use allowed action types and backend-shaped fields from "
        "get_available_controls.\n\n"
        f"{json.dumps(analyzer_report.model_dump(mode='json'), indent=2)}"
    )


def _planner_repair_prompt(
    analyzer_report: AnalyzerReport,
    previous_report: PlannerReport,
    coverage: PlannerCoverageResult,
) -> str:
    return (
        "Repair the previous PlannerReport. The deterministic planner coverage checker rejected "
        "it. You must call get_grid_state, get_available_controls, and build_candidate_archetypes "
        "again, then validate every action in every final candidate with validate_action_intent. "
        "Return a complete replacement PlannerReport, not a patch.\n\n"
        "Coverage issues:\n"
        f"{json.dumps(coverage.model_dump(mode='json'), indent=2)}\n\n"
        "Original AnalyzerReport:\n"
        f"{json.dumps(analyzer_report.model_dump(mode='json'), indent=2)}\n\n"
        "Rejected previous PlannerReport:\n"
        f"{json.dumps(previous_report.model_dump(mode='json'), indent=2)}"
    )


def _normalize_planner_report(report: PlannerReport) -> PlannerReport:
    candidates = []
    for candidate in report.candidates:
        normalized_sequence = []
        for intent in candidate.action_sequence:
            normalized_sequence.append(_normalize_action_intent(intent))
        candidates.append(candidate.model_copy(update={"action_sequence": normalized_sequence}))
    return report.model_copy(update={"candidates": candidates})


def _merge_traces(first: AgentRunTrace, second: AgentRunTrace) -> AgentRunTrace:
    return AgentRunTrace(
        response_ids=[*first.response_ids, *second.response_ids],
        tool_calls=[*first.tool_calls, *second.tool_calls],
    )


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
