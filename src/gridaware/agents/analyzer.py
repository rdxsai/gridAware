from __future__ import annotations

from typing import Any

from gridaware.agent_tools import responses_tool_definitions
from gridaware.agents.models import AnalyzerReport, AnalyzerRunResult
from gridaware.agents.prompts import ANALYZER_SYSTEM_PROMPT
from gridaware.agents.responses_runner import (
    DEFAULT_AGENT_MODEL,
    ResponsesClient,
    create_openai_client,
    json_schema_text_format,
    pydantic_strict_json_schema,
    run_responses_agent,
)
from gridaware.tool_executor import GridToolRuntime


ANALYZER_USER_PROMPT = """
Analyze the active grid scenario. Call get_grid_state first, then return the diagnostic JSON report.
""".strip()


def analyzer_tools() -> list[dict[str, Any]]:
    return [tool for tool in responses_tool_definitions() if tool["name"] == "get_grid_state"]


def run_analyzer_agent(
    runtime: GridToolRuntime,
    *,
    client: ResponsesClient | None = None,
    model: str = DEFAULT_AGENT_MODEL,
) -> AnalyzerRunResult:
    responses_client = client or create_openai_client()
    result = run_responses_agent(
        client=responses_client,
        model=model,
        system_prompt=ANALYZER_SYSTEM_PROMPT,
        user_prompt=ANALYZER_USER_PROMPT,
        tools=analyzer_tools(),
        runtime=runtime,
        text_format=json_schema_text_format(
            "analyzer_report",
            pydantic_strict_json_schema(AnalyzerReport),
            "Diagnostic grid analysis report for the planner.",
        ),
        initial_tool_choice={"type": "function", "name": "get_grid_state"},
    )
    report = AnalyzerReport.model_validate_json(result.output_text)
    return AnalyzerRunResult(
        report=_filter_overbroad_watchlists(report),
        trace=result.trace,
    )


def _filter_overbroad_watchlists(report: AnalyzerReport) -> AnalyzerReport:
    return report.model_copy(
        update={
            "watchlist_lines": [
                item
                for item in report.watchlist_lines
                if item.element_id not in report.violating_lines and 85.0 <= item.observed < item.limit
            ],
            "watchlist_buses": [
                item
                for item in report.watchlist_buses
                if item.element_id not in report.violating_buses
                and (0.95 <= item.observed <= 0.97 or 1.03 <= item.observed <= 1.05)
            ],
            "watchlist_data_centers": [
                item
                for item in report.watchlist_data_centers
                if item.element_id not in report.violating_data_centers
                and (0.95 <= item.observed <= 0.97 or 1.03 <= item.observed <= 1.05)
            ],
        }
    )
