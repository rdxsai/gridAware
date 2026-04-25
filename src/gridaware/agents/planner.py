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
    allowed_names = {"get_grid_state", "get_available_controls"}
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
            "Ranked mitigation action intents for later simulation.",
        ),
        initial_tool_choice={"type": "function", "name": "get_grid_state"},
        max_tool_rounds=5,
    )
    report = PlannerReport.model_validate_json(result.output_text)
    return PlannerRunResult(report=report, trace=result.trace)


def _planner_user_prompt(analyzer_report: AnalyzerReport) -> str:
    return (
        "Create a mitigation plan from this AnalyzerReport. "
        "Call get_grid_state and get_available_controls before returning the final JSON.\n\n"
        f"{json.dumps(analyzer_report.model_dump(mode='json'), indent=2)}"
    )
