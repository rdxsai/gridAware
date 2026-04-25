from gridaware.models import ActionIntent
from gridaware.pandapower_simulator import (
    simulate_action_intent_on_pandapower,
    simulate_action_sequence_on_pandapower,
    simulate_candidate_sequences_on_pandapower,
)
from gridaware.scenarios import load_agent_scenario


def test_pandapower_simulator_runs_action_intent_on_copied_net() -> None:
    bundle = load_agent_scenario("mv_data_center_spike")
    result = simulate_action_intent_on_pandapower(
        bundle,
        ActionIntent(
            type="shift_data_center_load",
            from_dc="DC_A",
            to_dc="DC_B",
            mw=10.0,
        ),
    )

    assert result["power_flow_converged"] is True
    assert result["after_state"]["scenario_id"] == "mv_data_center_spike"
    assert result["diff"]["score_change"]["after"] >= 0
    assert result["diff"]["line_loading_changes"]
    assert bundle.grid_state.data_centers[0].load_mw == 80.0


def test_pandapower_simulator_resolves_case33bw_spike_with_local_flexibility() -> None:
    bundle = load_agent_scenario("case33bw_data_center_spike")
    result = simulate_action_intent_on_pandapower(
        bundle,
        ActionIntent(
            type="dispatch_battery",
            battery_id="BAT_A",
            target_dc="DC_A",
            mw=0.5,
        ),
    )

    assert result["power_flow_converged"] is True
    assert result["after_state"]["scenario_id"] == "case33bw_data_center_spike"
    assert result["diff"]["score_change"]["delta"] > 0
    assert result["diff"]["resolved_violations"] == [
        {"type": "line_overload", "element_id": "line_25"},
        {"type": "voltage_low", "element_id": "DC_A"},
    ]
    assert result["diff"]["remaining_violations"] == []
    assert bundle.grid_state.data_centers[0].load_mw == 0.5


def test_pandapower_simulator_hard_spike_single_action_is_partial() -> None:
    bundle = load_agent_scenario("case33bw_data_center_spike_hard")
    result = simulate_action_intent_on_pandapower(
        bundle,
        ActionIntent(
            type="dispatch_battery",
            battery_id="BAT_A",
            target_dc="DC_A",
            mw=0.25,
        ),
    )

    assert result["power_flow_converged"] is True
    assert result["after_state"]["scenario_id"] == "case33bw_data_center_spike_hard"
    assert result["diff"]["score_change"]["delta"] > 0
    assert result["diff"]["resolved_violations"] == []
    assert {
        (violation["type"], violation["element_id"])
        for violation in result["diff"]["remaining_violations"]
    } == {
        ("line_overload", "line_25"),
        ("voltage_low", "DC_A"),
    }


def test_pandapower_simulator_sequence_resolves_hard_spike_cumulatively() -> None:
    bundle = load_agent_scenario("case33bw_data_center_spike_hard")
    result = simulate_action_sequence_on_pandapower(
        bundle,
        [
            ActionIntent(
                type="dispatch_battery",
                battery_id="BAT_A",
                target_dc="DC_A",
                mw=0.25,
            ),
            ActionIntent(
                type="curtail_flexible_load",
                dc="DC_A",
                mw=0.25,
            ),
            ActionIntent(
                type="increase_local_generation",
                generator_id="GEN_A",
                target_dc="DC_A",
                mw=0.25,
            ),
        ],
    )

    assert result["sequence_completed"] is True
    assert result["failed_step_index"] is None
    assert len(result["step_results"]) == 3
    assert result["final_diff"]["resolved_violations"] == [
        {"type": "line_overload", "element_id": "line_25"},
        {"type": "voltage_low", "element_id": "DC_A"},
    ]
    assert result["final_diff"]["remaining_violations"] == []
    assert result["final_state"]["grid_health_score"] > bundle.grid_state.grid_health_score


def test_pandapower_simulator_sequence_stops_when_control_is_depleted() -> None:
    bundle = load_agent_scenario("case33bw_data_center_spike_hard")
    result = simulate_action_sequence_on_pandapower(
        bundle,
        [
            ActionIntent(
                type="dispatch_battery",
                battery_id="BAT_A",
                target_dc="DC_A",
                mw=0.25,
            ),
            ActionIntent(
                type="dispatch_battery",
                battery_id="BAT_A",
                target_dc="DC_A",
                mw=0.25,
            ),
        ],
    )

    assert result["sequence_completed"] is False
    assert result["failed_step_index"] == 2
    assert result["step_results"][0]["validation_passed"] is True
    assert result["step_results"][1]["validation_passed"] is False
    assert "has only 0.0 MW available" in result["step_results"][1]["validation_errors"][0]


def test_pandapower_simulator_batches_candidate_sequences_from_same_baseline() -> None:
    bundle = load_agent_scenario("case33bw_data_center_spike_hard")
    result = simulate_candidate_sequences_on_pandapower(
        bundle,
        [
            {
                "candidate_id": "candidate_1",
                "rank": 1,
                "action_intents": [
                    ActionIntent(
                        type="dispatch_battery",
                        battery_id="BAT_A",
                        target_dc="DC_A",
                        mw=0.25,
                    ).model_dump(mode="json")
                ],
            },
            {
                "candidate_id": "candidate_2",
                "rank": 2,
                "action_intents": [
                    ActionIntent(
                        type="curtail_flexible_load",
                        dc="DC_A",
                        mw=0.25,
                    ).model_dump(mode="json")
                ],
            },
        ],
    )

    assert result["ok"] is True
    assert len(result["candidate_results"]) == 2
    assert result["candidate_results"][0]["result"]["before_state"]["grid_health_score"] == 8
    assert result["candidate_results"][1]["result"]["before_state"]["grid_health_score"] == 8
