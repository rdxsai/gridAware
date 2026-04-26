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


def test_planner_agent_uses_controls_and_validation_tools() -> None:
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
            function_call_response("planner_3", "build_candidate_archetypes", "planner_archetypes"),
            function_call_response(
                "planner_4",
                "validate_action_intent",
                "planner_validate_generation",
                json.dumps({"action_intent": _backend_intent("increase_local_generation", 10.0)}),
            ),
            function_call_response(
                "planner_5",
                "validate_action_intent",
                "planner_validate_shift",
                json.dumps({"action_intent": _backend_intent("shift_data_center_load", 15.0)}),
            ),
            function_call_response(
                "planner_6",
                "validate_action_intent",
                "planner_validate_curtail",
                json.dumps({"action_intent": _backend_intent("curtail_flexible_load", 8.0)}),
            ),
            function_call_response(
                "planner_7",
                "validate_action_intent",
                "planner_validate_battery",
                json.dumps({"action_intent": _backend_intent("dispatch_battery", 10.0)}),
            ),
            final_response(
                "planner_8",
                {
                    "scenario_id": "mv_data_center_spike",
                    "planning_summary": "Reduce DC_A stress with feasible action intents.",
                    "primary_objectives": [
                        "Reduce line_4 loading below 100 percent.",
                        "Restore DC_A voltage to at least 0.95 pu.",
                    ],
                    "primitive_action_inventory": [
                        _primitive("shift_data_center_load", "DC_A->DC_B", 15.0, "MW"),
                        _primitive("dispatch_battery", "BAT_A", 10.0, "MW"),
                        _primitive("increase_local_generation", "GEN_A", 10.0, "MW"),
                        _primitive("curtail_flexible_load", "DC_A", 8.0, "MW"),
                    ],
                    "candidates": [
                        _candidate(1, "minimal_candidate", [_generation_intent(10.0)]),
                        _candidate(
                            2,
                            "thermal_first_candidate",
                            [_shift_intent(15.0), _curtail_intent(8.0)],
                        ),
                        _candidate(3, "voltage_first_candidate", [_battery_intent(10.0)]),
                        _candidate(
                            4,
                            "balanced_candidate",
                            [_shift_intent(15.0), _generation_intent(10.0)],
                        ),
                        _candidate(
                            5,
                            "max_feasible_composite_candidate",
                            [
                                _shift_intent(15.0),
                                _curtail_intent(8.0),
                                _battery_intent(10.0),
                                _generation_intent(10.0),
                            ],
                        ),
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
        "build_candidate_archetypes",
        "validate_action_intent",
    ]
    assert client.responses.calls[0]["tool_choice"] == {
        "type": "function",
        "name": "get_grid_state",
    }
    assert planner_result.trace.tool_calls[0].name == "get_grid_state"
    assert planner_result.trace.tool_calls[1].name == "get_available_controls"
    assert planner_result.trace.tool_calls[2].name == "build_candidate_archetypes"
    assert planner_result.trace.tool_calls[3].name == "validate_action_intent"
    assert planner_result.trace.tool_calls[4].name == "validate_action_intent"
    assert planner_result.trace.tool_calls[5].name == "validate_action_intent"
    assert planner_result.trace.tool_calls[6].name == "validate_action_intent"
    intent = planner_result.report.candidates[0].action_sequence[0]
    assert intent.mw == 10.0
    assert intent.type == "increase_local_generation"
    assert intent.to_dc is None
    assert intent.battery_id is None
    assert intent.dc is None
    assert planner_result.report.requires_simulation is True


def _candidate(rank: int, archetype: str, action_sequence: list[dict]) -> dict:
    return {
        "rank": rank,
        "archetype": archetype,
        "action_sequence": action_sequence,
        "validation_passed": True,
        "validation_passed_checks": ["backend validation passed"],
        "target_violations": ["line_4", "DC_A"],
        "feasibility_checks": ["all action-specific feasibility checks passed"],
        "expected_effect": "Reduce active grid stress.",
        "rationale": "Candidate covers a required planner archetype.",
        "risk_notes": ["Simulation must verify no new violation is created."],
        "planner_confidence": "high",
    }


def _primitive(action_type: str, target: str, max_value: float, units: str) -> dict:
    return {
        "action_type": action_type,
        "target": target,
        "max_value": max_value,
        "units": units,
        "primary_effect": "thermal_and_voltage",
        "backend_action_intent": _backend_intent(action_type, max_value),
        "rationale": f"{action_type} is available for {target}.",
    }


def _backend_intent(action_type: str, value: float) -> dict:
    if action_type == "shift_data_center_load":
        return _backend_base(action_type) | {"from_dc": "DC_A", "to_dc": "DC_B", "mw": value}
    if action_type == "dispatch_battery":
        return _backend_base(action_type) | {
            "battery_id": "BAT_A",
            "target_dc": "DC_A",
            "mw": value,
        }
    if action_type == "increase_local_generation":
        return _backend_base(action_type) | {
            "generator_id": "GEN_A",
            "target_dc": "DC_A",
            "mw": value,
        }
    return _backend_base(action_type) | {"dc": "DC_A", "mw": value}


def _backend_base(action_type: str) -> dict:
    return {
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


def _shift_intent(mw: float) -> dict:
    return _planner_intent(
        _backend_base("shift_data_center_load")
        | {
            "from_dc": "DC_A",
            "to_dc": "DC_B",
            "mw": mw,
        },
        "Shift flexible load from DC_A to DC_B.",
        "DC_A",
        None,
        "MW",
    )


def _curtail_intent(mw: float) -> dict:
    return _planner_intent(
        _backend_base("curtail_flexible_load")
        | {
            "dc": "DC_A",
            "mw": mw,
        },
        "Curtail flexible load at DC_A.",
        "DC_A",
        None,
        "MW",
    )


def _battery_intent(mw: float) -> dict:
    return _planner_intent(
        _backend_base("dispatch_battery")
        | {
            "battery_id": "BAT_A",
            "target_dc": "DC_A",
            "mw": mw,
        },
        "Dispatch battery support near DC_A.",
        "DC_A",
        "BAT_A",
        "MW",
    )


def _generation_intent(mw: float) -> dict:
    return _planner_intent(
        _backend_base("increase_local_generation")
        | {
            "generator_id": "GEN_A",
            "target_dc": "DC_A",
            "mw": mw,
        },
        "Increase local generation near DC_A.",
        "DC_A",
        "GEN_A",
        "MW",
    )


def _planner_intent(
    backend_intent: dict,
    summary: str,
    target_element: str | None,
    control_asset: str | None,
    units: str,
) -> dict:
    return backend_intent | {
        "intent_summary": summary,
        "target_element": target_element,
        "control_asset": control_asset,
        "setpoint": None,
        "units": units,
    }
