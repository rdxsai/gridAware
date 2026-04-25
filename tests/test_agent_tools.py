import json

from gridaware.agent_tools import responses_tool_definitions
from gridaware.tool_executor import GridToolRuntime


def test_responses_tool_definitions_are_strict() -> None:
    tools = responses_tool_definitions()

    assert [tool["name"] for tool in tools] == [
        "get_grid_state",
        "propose_grid_actions",
        "get_available_controls",
        "simulate_action",
        "evaluate_action_result",
        "apply_action",
        "compare_grid_states",
    ]
    assert all(tool["type"] == "function" for tool in tools)
    assert all(tool["strict"] is True for tool in tools)
    assert all(tool["parameters"]["additionalProperties"] is False for tool in tools)


def test_tool_runtime_simulates_evaluates_and_applies_agent_intent() -> None:
    runtime = GridToolRuntime()
    simulation = json.loads(
        runtime.execute(
            "simulate_action",
            {
                "action_id": None,
                "action_intent": {
                    "type": "shift_data_center_load",
                    "from_dc": "DC_A",
                    "to_dc": "DC_B",
                    "battery_id": None,
                    "generator_id": None,
                    "target_dc": None,
                    "dc": None,
                    "mw": 15.0,
                },
            },
        )
    )

    action_id = simulation["simulation"]["action_id"]
    evaluation = json.loads(runtime.execute("evaluate_action_result", {"action_id": action_id}))
    applied = json.loads(runtime.execute("apply_action", {"action_id": action_id}))
    comparison = json.loads(runtime.execute("compare_grid_states", {}))

    assert simulation["ok"] is True
    assert simulation["simulation"]["success"] is True
    assert action_id == "agent_intent_1"
    assert evaluation["evaluation"]["accepted"] is True
    assert applied["applied"] is True
    assert comparison["summary"]["violations_after"] == 0


def test_tool_runtime_rejects_unsimulated_apply() -> None:
    runtime = GridToolRuntime()

    result = json.loads(runtime.execute("apply_action", {"action_id": "A999"}))

    assert result == {"ok": False, "error": "Action has not been simulated: A999"}


def test_tool_runtime_returns_available_controls() -> None:
    runtime = GridToolRuntime()

    result = json.loads(runtime.execute("get_available_controls", {}))

    assert result["ok"] is True
    assert "shift_data_center_load" in result["allowed_action_types"]
    assert result["data_centers"][0]["receiving_headroom_mw"] == 15.0
    assert result["batteries"][0]["id"] == "BAT_A"


def test_tool_runtime_rejects_infeasible_agent_intent() -> None:
    runtime = GridToolRuntime()

    result = json.loads(
        runtime.execute(
            "simulate_action",
            {
                "action_id": None,
                "action_intent": {
                    "type": "shift_data_center_load",
                    "from_dc": "DC_A",
                    "to_dc": "DC_B",
                    "battery_id": None,
                    "generator_id": None,
                    "target_dc": None,
                    "dc": None,
                    "mw": 50.0,
                },
            },
        )
    )

    assert result["ok"] is False
    assert "flexible load" in result["error"]
