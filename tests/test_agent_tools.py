import json

from gridaware.agent_tools import responses_tool_definitions
from gridaware.scenarios import load_agent_scenario
from gridaware.tool_executor import GridToolRuntime


def test_responses_tool_definitions_are_strict() -> None:
    tools = responses_tool_definitions()

    assert [tool["name"] for tool in tools] == [
        "get_grid_state",
        "propose_grid_actions",
        "get_available_controls",
        "validate_action_intent",
        "simulate_action",
        "simulate_action_intent",
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
    assert (
        "target_dc.receiving_headroom_mw"
        in result["action_feasibility_policy"]["dispatch_battery"]["forbidden_checks"]
    )
    assert (
        "mw <= to_dc.receiving_headroom_mw"
        in result["action_feasibility_policy"]["shift_data_center_load"]["valid_checks"]
    )


def test_tool_runtime_validates_action_intent() -> None:
    runtime = GridToolRuntime()

    valid = json.loads(
        runtime.execute(
            "validate_action_intent",
            {
                "action_intent": {
                    "type": "shift_data_center_load",
                    "from_dc": "DC_A",
                    "to_dc": "DC_B",
                    "battery_id": None,
                    "generator_id": None,
                    "target_dc": None,
                    "dc": None,
                    "mw": 15.0,
                }
            },
        )
    )
    invalid = json.loads(
        runtime.execute(
            "validate_action_intent",
            {
                "action_intent": {
                    "type": "shift_data_center_load",
                    "from_dc": "DC_A",
                    "to_dc": "DC_B",
                    "battery_id": None,
                    "generator_id": None,
                    "target_dc": None,
                    "dc": None,
                    "mw": 50.0,
                }
            },
        )
    )

    assert valid["validation"]["valid"] is True
    assert valid["validation"]["normalized_action_intent"]["to_dc"] == "DC_B"
    assert invalid["validation"]["valid"] is False
    assert invalid["validation"]["failed_checks"]


def test_tool_runtime_simulates_action_intent_with_pandapower_bundle() -> None:
    runtime = GridToolRuntime(scenario_bundle=load_agent_scenario())

    result = json.loads(
        runtime.execute(
            "simulate_action_intent",
            {
                "action_intent": {
                    "type": "curtail_flexible_load",
                    "from_dc": None,
                    "to_dc": None,
                    "battery_id": None,
                    "generator_id": None,
                    "target_dc": None,
                    "dc": "DC_A",
                    "mw": 8.0,
                }
            },
        )
    )

    assert result["ok"] is True
    assert result["power_flow_converged"] is True
    assert result["after_state"]["scenario_id"] == "mv_data_center_spike"
    assert result["diff"]["voltage_changes"]


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
