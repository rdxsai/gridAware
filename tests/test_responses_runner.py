import json
from types import SimpleNamespace

from gridaware.agents.models import AnalyzerReport
from gridaware.agents.responses_runner import (
    json_schema_text_format,
    pydantic_strict_json_schema,
    run_responses_agent,
)
from gridaware.agent_tools import responses_tool_definitions
from gridaware.scenarios import load_agent_grid
from gridaware.tool_executor import GridToolRuntime


class FakeResponses:
    def __init__(self) -> None:
        self.calls = 0
        self.kwargs = []

    def create(self, **kwargs):
        self.calls += 1
        self.kwargs.append(kwargs)
        if self.calls == 1:
            return SimpleNamespace(
                id="resp_1",
                output_text="",
                output=[
                    SimpleNamespace(
                        type="function_call",
                        name="get_grid_state",
                        arguments="{}",
                        call_id="call_1",
                    )
                ],
            )
        return SimpleNamespace(
            id="resp_2",
            output_text=json.dumps(
                {
                    "scenario_id": "mv_data_center_spike",
                    "summary": "High stress from line_4 overload and low voltage at DC_A.",
                    "active_violations": [],
                    "violating_lines": ["line_4"],
                    "violating_buses": ["DC_A"],
                    "violating_data_centers": ["DC_A"],
                    "watchlist_lines": [],
                    "watchlist_buses": [],
                    "watchlist_data_centers": [],
                    "risk_level": "high",
                    "planner_focus": ["Reduce line_4 loading below 100 percent."],
                    "forbidden_next_steps": ["Do not apply actions without simulation."],
                }
            ),
            output=[],
        )


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


def test_pydantic_schema_is_responses_format_ready() -> None:
    schema = pydantic_strict_json_schema(AnalyzerReport)

    assert "$defs" not in schema
    assert schema["additionalProperties"] is False
    assert schema["properties"]["active_violations"]["items"]["additionalProperties"] is False


def test_responses_runner_executes_tool_calls_and_returns_trace() -> None:
    client = FakeClient()
    result = run_responses_agent(
        client=client,
        model="test-model",
        system_prompt="Return JSON.",
        user_prompt="Analyze.",
        tools=[tool for tool in responses_tool_definitions() if tool["name"] == "get_grid_state"],
        runtime=GridToolRuntime(load_agent_grid()),
        text_format=json_schema_text_format(
            "analyzer_report",
            pydantic_strict_json_schema(AnalyzerReport),
            "Analyzer report.",
        ),
    )

    report = AnalyzerReport.model_validate_json(result.output_text)
    assert report.risk_level == "high"
    assert result.trace.response_ids == ["resp_1", "resp_2"]
    assert result.trace.tool_calls[0].name == "get_grid_state"
    assert client.responses.kwargs[1]["tool_choice"] == "auto"


def test_responses_runner_rejects_disallowed_tool_calls() -> None:
    class BadResponses(FakeResponses):
        def create(self, **kwargs):
            return SimpleNamespace(
                id="resp_bad",
                output_text="",
                output=[
                    SimpleNamespace(
                        type="function_call",
                        name="apply_action",
                        arguments='{"action_id":"A1"}',
                        call_id="call_bad",
                    )
                ],
            )

    class BadClient:
        responses = BadResponses()

    try:
        run_responses_agent(
            client=BadClient(),
            model="test-model",
            system_prompt="Return JSON.",
            user_prompt="Analyze.",
            tools=[tool for tool in responses_tool_definitions() if tool["name"] == "get_grid_state"],
            runtime=GridToolRuntime(load_agent_grid()),
            text_format=json_schema_text_format(
                "analyzer_report",
                pydantic_strict_json_schema(AnalyzerReport),
                "Analyzer report.",
            ),
        )
    except RuntimeError as exc:
        assert str(exc) == "Agent requested disallowed tool: apply_action"
    else:
        raise AssertionError("Expected disallowed tool call to be rejected")
