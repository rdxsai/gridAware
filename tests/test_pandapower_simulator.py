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
