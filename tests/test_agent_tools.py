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
        "simulate_action_sequence",
        "simulate_candidate_sequences",
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


def test_tool_runtime_returns_case33bw_scenario_specific_controls() -> None:
    runtime = GridToolRuntime(scenario_bundle=load_agent_scenario("case33bw_data_center_spike"))

    result = json.loads(runtime.execute("get_available_controls", {}))

    assert result["ok"] is True
    assert result["allowed_action_types"] == [
        "shift_data_center_load",
        "dispatch_battery",
        "increase_local_generation",
        "curtail_flexible_load",
        "adjust_reactive_support",
    ]
    assert result["data_centers"] == [
        {
            "id": "DC_A",
            "zone": "feeder_tail",
            "load_mw": 0.5,
            "flexible_mw": 0.5,
            "max_load_mw": 0.7,
            "receiving_headroom_mw": 0.2,
        },
        {
            "id": "DC_B",
            "zone": "mid_feeder",
            "load_mw": 0.25,
            "flexible_mw": 0.1,
            "max_load_mw": 0.8,
            "receiving_headroom_mw": 0.55,
        },
    ]
    assert result["batteries"] == [{"id": "BAT_A", "zone": "feeder_tail", "available_mw": 0.5}]
    assert result["local_generators"] == [
        {"id": "GEN_A", "zone": "feeder_tail", "available_headroom_mw": 0.5}
    ]
    assert result["reactive_resources"] == [
        {"id": "VAR_A", "zone": "feeder_tail", "available_mvar": 0.1}
    ]
    assert result["control_assets"]["reactive_resources"] == result["reactive_resources"]
    assert result["action_feasibility_policy"]["adjust_reactive_support"] == {
        "required_fields": ["resource_id", "target_bus", "q_mvar"],
        "valid_checks": [
            "resource_id exists in reactive_resources",
            "target_bus exists in bus_voltages",
            "q_mvar <= resource.available_mvar",
            "resource.zone should match target_bus zone or support the target zone",
        ],
        "forbidden_checks": [
            "mw",
            "target_dc.receiving_headroom_mw",
            "battery.available_mw",
            "generator.available_headroom_mw",
        ],
    }


def test_tool_runtime_returns_no_controls_for_untouched_case33bw_baseline() -> None:
    runtime = GridToolRuntime(scenario_bundle=load_agent_scenario("baseline_case33bw"))

    result = json.loads(runtime.execute("get_available_controls", {}))

    assert result["ok"] is True
    assert result["allowed_action_types"] == []
    assert result["data_centers"] == []
    assert result["batteries"] == []
    assert result["local_generators"] == []


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


def test_tool_runtime_validates_reactive_support_action_intent() -> None:
    runtime = GridToolRuntime(
        scenario_bundle=load_agent_scenario("case33bw_data_center_spike_hard")
    )

    valid = json.loads(
        runtime.execute(
            "validate_action_intent",
            {
                "action_intent": {
                    "type": "adjust_reactive_support",
                    "from_dc": None,
                    "to_dc": None,
                    "battery_id": None,
                    "generator_id": None,
                    "target_dc": None,
                    "dc": None,
                    "resource_id": "VAR_A",
                    "target_bus": "DC_A",
                    "q_mvar": 0.1,
                    "mw": None,
                }
            },
        )
    )
    invalid = json.loads(
        runtime.execute(
            "validate_action_intent",
            {
                "action_intent": {
                    "type": "adjust_reactive_support",
                    "from_dc": None,
                    "to_dc": None,
                    "battery_id": None,
                    "generator_id": None,
                    "target_dc": None,
                    "dc": None,
                    "resource_id": "VAR_A",
                    "target_bus": "DC_A",
                    "q_mvar": 0.2,
                    "mw": None,
                }
            },
        )
    )

    assert valid["validation"]["valid"] is True
    assert valid["validation"]["normalized_action_intent"]["resource_id"] == "VAR_A"
    assert valid["validation"]["normalized_action_intent"]["q_mvar"] == 0.1
    assert invalid["validation"]["valid"] is False
    assert "q_mvar <= resource.available_mvar" in invalid["validation"]["failed_checks"][0]


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


def test_tool_runtime_simulates_action_sequence_with_pandapower_bundle() -> None:
    runtime = GridToolRuntime(
        scenario_bundle=load_agent_scenario("case33bw_data_center_spike_hard")
    )

    result = json.loads(
        runtime.execute(
            "simulate_action_sequence",
            {
                "action_intents": [
                    {
                        "type": "dispatch_battery",
                        "from_dc": None,
                        "to_dc": None,
                        "battery_id": "BAT_A",
                        "generator_id": None,
                        "target_dc": "DC_A",
                        "dc": None,
                        "mw": 0.25,
                    },
                    {
                        "type": "curtail_flexible_load",
                        "from_dc": None,
                        "to_dc": None,
                        "battery_id": None,
                        "generator_id": None,
                        "target_dc": None,
                        "dc": "DC_A",
                        "mw": 0.25,
                    },
                    {
                        "type": "increase_local_generation",
                        "from_dc": None,
                        "to_dc": None,
                        "battery_id": None,
                        "generator_id": "GEN_A",
                        "target_dc": "DC_A",
                        "dc": None,
                        "mw": 0.25,
                    },
                ]
            },
        )
    )

    assert result["ok"] is True
    assert result["sequence_completed"] is True
    assert len(result["step_results"]) == 3
    assert result["final_state"]["scenario_id"] == "case33bw_data_center_spike_hard"
    assert result["final_diff"]["score_change"]["delta"] > 0
    assert result["final_diff"]["remaining_violations"] == []


def test_tool_runtime_simulates_candidate_sequences_from_same_baseline() -> None:
    runtime = GridToolRuntime(
        scenario_bundle=load_agent_scenario("case33bw_data_center_spike_hard")
    )

    result = json.loads(
        runtime.execute(
            "simulate_candidate_sequences",
            {
                "candidates": [
                    {
                        "candidate_id": "candidate_1",
                        "rank": 1,
                        "action_intents": [
                            {
                                "type": "dispatch_battery",
                                "from_dc": None,
                                "to_dc": None,
                                "battery_id": "BAT_A",
                                "generator_id": None,
                                "target_dc": "DC_A",
                                "dc": None,
                                "mw": 0.25,
                            }
                        ],
                    },
                    {
                        "candidate_id": "candidate_2",
                        "rank": 2,
                        "action_intents": [
                            {
                                "type": "curtail_flexible_load",
                                "from_dc": None,
                                "to_dc": None,
                                "battery_id": None,
                                "generator_id": None,
                                "target_dc": None,
                                "dc": "DC_A",
                                "mw": 0.25,
                            }
                        ],
                    },
                ]
            },
        )
    )

    assert result["ok"] is True
    assert [candidate["candidate_id"] for candidate in result["candidate_results"]] == [
        "candidate_1",
        "candidate_2",
    ]
    assert result["candidate_results"][0]["result"]["before_state"]["grid_health_score"] == 8
    assert result["candidate_results"][1]["result"]["before_state"]["grid_health_score"] == 8


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
