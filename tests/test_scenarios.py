from gridaware.scenarios import load_agent_grid


def test_default_agent_grid_uses_benchmark_backed_mv_variant() -> None:
    state = load_agent_grid()

    assert state.scenario_id == "mv_data_center_spike"
    assert {data_center.id for data_center in state.data_centers} == {"DC_A", "DC_B"}
    assert any(
        violation.type == "line_overload" and violation.element_id == "line_4"
        for violation in state.violations
    )
    assert any(
        violation.type == "voltage_low" and violation.element_id == "DC_A"
        for violation in state.violations
    )


def test_agent_grid_variants_are_not_identical() -> None:
    mv_state = load_agent_grid("mv_data_center_spike")
    lv_state = load_agent_grid("lv_edge_data_center")

    assert mv_state.scenario_id != lv_state.scenario_id
    assert len(mv_state.line_loadings) != len(lv_state.line_loadings)
    assert mv_state.data_centers[0].zone != lv_state.data_centers[0].zone
