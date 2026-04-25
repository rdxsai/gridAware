import json
from types import SimpleNamespace

from gridaware.agents.analyzer import run_analyzer_agent
from gridaware.agents.planner import planner_tools, run_planner_agent
from gridaware.scenarios import load_agent_grid
from gridaware.tool_executor import GridToolRuntime


class FakeResponses:
    def __init__(self, outputs: list[object]) -> None:
        self.outputs = outputs
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.outputs.pop(0)


class FakeClient:
    def __init__(self, outputs: list[object]) -> None:
        self.responses = FakeResponses(outputs)


def function_call_response(response_id: str, name: str, call_id: str, arguments: str = "{}"):
    return SimpleNamespace(
        id=response_id,
        output_text="",
        output=[
            SimpleNamespace(
                type="function_call",
                name=name,
                arguments=arguments,
                call_id=call_id,
            )
        ],
    )


def final_response(response_id: str, payload: dict):
    return SimpleNamespace(id=response_id, output_text=json.dumps(payload), output=[])


def test_planner_agent_uses_grid_state_and_available_controls() -> None:
    runtime = GridToolRuntime(load_agent_grid())
    analyzer_result = run_analyzer_agent(
        runtime,
        client=FakeClient(
            [
                function_call_response("analyzer_1", "get_grid_state", "call_grid"),
                final_response(
                    "analyzer_2",
                    {
                        "scenario_id": "mv_data_center_spike",
                        "summary": "line_4 and DC_A are violating.",
                        "active_violations": [],
                        "violating_lines": ["line_4"],
                        "violating_buses": ["DC_A"],
                        "violating_data_centers": ["DC_A"],
                        "watchlist_lines": [],
                        "watchlist_buses": [],
                        "watchlist_data_centers": [],
                        "risk_level": "high",
                        "planner_focus": ["Reduce line_4 loading below 100 percent."],
                        "forbidden_next_steps": [],
                    },
                ),
            ]
        ),
        model="test-model",
    )
    client = FakeClient(
        [
            function_call_response("planner_1", "get_grid_state", "planner_grid"),
            function_call_response("planner_2", "get_available_controls", "planner_controls"),
            final_response(
                "planner_3",
                {
                    "scenario_id": "mv_data_center_spike",
                    "planning_summary": "Reduce DC_A stress with feasible action intents.",
                    "primary_objectives": [
                        "Reduce line_4 loading below 100 percent.",
                        "Restore DC_A voltage to at least 0.95 pu.",
                    ],
                    "candidates": [
                        {
                            "rank": 1,
                            "action_intent": {
                                "type": "increase_local_generation",
                                "from_dc": "DC_A",
                                "to_dc": "DC_A",
                                "battery_id": "BAT_A",
                                "generator_id": "GEN_A",
                                "target_dc": "DC_A",
                                "dc": "DC_A",
                                "mw": 10.0,
                            },
                            "target_violations": ["line_4", "DC_A"],
                            "feasibility_checks": [
                                "DC_A flexible_mw is 24, which is >= 10.",
                                "DC_B receiving headroom is 23, which is >= 10.",
                            ],
                            "expected_effect": "Reduce DC_A load and relieve upstream stress.",
                            "rationale": "A partial shift targets both active violations.",
                            "risk_notes": ["Simulation must verify no watchlist line worsens."],
                            "planner_confidence": "high",
                        }
                    ],
                    "rejected_options": ["Do not apply without simulation."],
                    "requires_simulation": True,
                },
            ),
        ]
    )

    planner_result = run_planner_agent(
        runtime,
        analyzer_result.report,
        client=client,
        model="test-model",
    )

    assert [tool["name"] for tool in planner_tools()] == [
        "get_grid_state",
        "get_available_controls",
    ]
    assert client.responses.calls[0]["tool_choice"] == {
        "type": "function",
        "name": "get_grid_state",
    }
    assert planner_result.trace.tool_calls[0].name == "get_grid_state"
    assert planner_result.trace.tool_calls[1].name == "get_available_controls"
    assert planner_result.report.candidates[0].action_intent.mw == 10.0
    assert planner_result.report.candidates[0].action_intent.type == "increase_local_generation"
    assert planner_result.report.candidates[0].action_intent.to_dc is None
    assert planner_result.report.candidates[0].action_intent.battery_id is None
    assert planner_result.report.candidates[0].action_intent.dc is None
    assert planner_result.report.requires_simulation is True
