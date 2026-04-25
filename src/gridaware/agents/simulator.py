from __future__ import annotations

import json
from typing import Any

from gridaware.agent_tools import responses_tool_definitions
from gridaware.agents.models import PlannerReport, SimulatorReport, SimulatorRunResult
from gridaware.agents.prompts import SIMULATOR_SYSTEM_PROMPT
from gridaware.agents.responses_runner import (
    DEFAULT_AGENT_MODEL,
    ResponsesClient,
    create_openai_client,
    json_schema_text_format,
    pydantic_strict_json_schema,
    run_responses_agent,
)
from gridaware.tool_executor import GridToolRuntime


def simulator_tools() -> list[dict[str, Any]]:
    return [
        tool for tool in responses_tool_definitions() if tool["name"] == "simulate_action_sequence"
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
        user_prompt=_simulator_user_prompt(planner_report),
        tools=simulator_tools(),
        runtime=runtime,
        text_format=json_schema_text_format(
            "simulator_report",
            pydantic_strict_json_schema(SimulatorReport),
            "Simulation report comparing before and after grid states for planner candidates.",
        ),
        initial_tool_choice="auto",
        max_tool_rounds=max(4, len(planner_report.candidates) + 4),
    )
    return SimulatorRunResult(
        report=SimulatorReport.model_validate_json(result.output_text),
        trace=result.trace,
    )


def _simulator_user_prompt(planner_report: PlannerReport) -> str:
    return (
        "Simulate each validated action sequence candidate in this PlannerReport. "
        "Call simulate_action_sequence once per candidate before returning final JSON.\n\n"
        f"{json.dumps(planner_report.model_dump(mode='json'), indent=2)}"
    )
