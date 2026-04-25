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
    allowed_names = {"get_grid_state"}
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
        max_tool_rounds=10,
    )
    report = PlannerReport.model_validate_json(result.output_text)
    return PlannerRunResult(report=_normalize_planner_report(report), trace=result.trace)


def _planner_user_prompt(analyzer_report: AnalyzerReport) -> str:
    return (
        "Create a mitigation plan from this AnalyzerReport. "
        "Call get_grid_state before returning the final JSON. "
        "Do not call get_available_controls; reason freely from the grid state and violations.\n\n"
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
    return intent
