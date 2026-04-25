import json
from types import SimpleNamespace

from gridaware.orchestrator import GridOrchestrator


class FakeResponses:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
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
                    "active_violations": [
                        {
                            "type": "line_overload",
                            "element_id": "line_4",
                            "observed": 111.1,
                            "limit": 100.0,
                            "units": "percent",
                            "severity": "high",
                            "explanation": "line_4 exceeds its thermal limit.",
                        }
                    ],
                    "violating_lines": ["line_4"],
                    "violating_buses": ["DC_A"],
                    "violating_data_centers": ["DC_A"],
                    "watchlist_lines": [
                        {
                            "element_id": "line_2",
                            "observed": 90.0,
                            "limit": 100.0,
                            "units": "percent",
                            "reason": "line_2 is near the thermal limit but not violating.",
                        }
                    ],
                    "watchlist_buses": [
                        {
                            "element_id": "DC_B",
                            "observed": 0.989,
                            "limit": 0.95,
                            "units": "pu",
                            "reason": "Overbroad model output that should be filtered.",
                        }
                    ],
                    "watchlist_data_centers": [
                        {
                            "element_id": "DC_B",
                            "observed": 0.989,
                            "limit": 0.95,
                            "units": "pu",
                            "reason": "Overbroad model output that should be filtered.",
                        }
                    ],
                    "risk_level": "high",
                    "planner_focus": [
                        "Reduce line_4 loading below 100 percent.",
                        "Restore DC_A voltage to at least 0.95 pu.",
                    ],
                    "forbidden_next_steps": ["Do not apply actions without simulation."],
                }
            ),
            output=[],
        )


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


def test_orchestrator_runs_analyzer_with_only_grid_state_tool() -> None:
    client = FakeClient()
    result = GridOrchestrator(client=client, model="test-model").run_analyzer()

    first_call = client.responses.calls[0]
    assert result.report.risk_level == "high"
    assert [tool["name"] for tool in first_call["tools"]] == ["get_grid_state"]
    assert first_call["parallel_tool_calls"] is False
    assert first_call["tool_choice"] == {"type": "function", "name": "get_grid_state"}
    assert result.trace.tool_calls[0].name == "get_grid_state"
    assert result.report.violating_lines == ["line_4"]
    assert result.report.watchlist_lines[0].element_id == "line_2"
    assert result.report.watchlist_buses == []
    assert result.report.watchlist_data_centers == []
