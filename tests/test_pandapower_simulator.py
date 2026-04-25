from gridaware.models import ActionIntent
from gridaware.pandapower_simulator import simulate_action_intent_on_pandapower
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
