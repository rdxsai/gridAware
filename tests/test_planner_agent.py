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


def test_planner_agent_uses_grid_state_only_for_freeform_planning() -> None:
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
            final_response(
                "planner_2",
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
                            "action_sequence": [
                                {
                                    "type": "increase_local_generation",
                                    "intent_summary": "Increase local generation near DC_A.",
                                    "from_dc": "DC_A",
                                    "to_dc": "DC_A",
                                    "battery_id": "BAT_A",
                                    "generator_id": "GEN_A",
                                    "target_dc": "DC_A",
                                    "dc": "DC_A",
                                    "resource_id": None,
                                    "target_bus": None,
                                    "q_mvar": None,
                                    "target_element": "DC_A",
                                    "control_asset": "GEN_A",
                                    "setpoint": None,
                                    "units": "MW",
                                    "mw": 10.0,
                                }
                            ],
                            "validation_passed": True,
                            "validation_passed_checks": [
                                "generator_id exists in local_generators: GEN_A",
                                "target_dc exists in data_centers: DC_A",
                            ],
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
    ]
    assert client.responses.calls[0]["tool_choice"] == {
        "type": "function",
        "name": "get_grid_state",
    }
    assert planner_result.trace.tool_calls[0].name == "get_grid_state"
    intent = planner_result.report.candidates[0].action_sequence[0]
    assert intent.mw == 10.0
    assert intent.type == "increase_local_generation"
    assert intent.to_dc is None
    assert intent.battery_id is None
    assert intent.dc is None
    assert planner_result.report.requires_simulation is True
