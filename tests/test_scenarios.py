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


def test_baseline_case33bw_preserves_untouched_benchmark() -> None:
    state = load_agent_grid("baseline_case33bw")

    assert state.scenario_id == "baseline_case33bw"
    assert state.metadata is not None
    assert state.metadata.base_network == "pandapower.networks.case33bw()"
    assert state.metadata.scenario_type == "untouched_benchmark"
    assert state.data_centers == []
    assert state.batteries == []
    assert state.local_generators == []
    assert state.metadata.modifications == [
        "No modifications. This scenario loads pandapower.networks.case33bw() as-is."
    ]


def test_case33bw_data_center_spike_has_clear_documented_stress() -> None:
    state = load_agent_grid("case33bw_data_center_spike")

    assert state.metadata is not None
    assert state.metadata.base_network == "pandapower.networks.case33bw()"
    assert state.metadata.scenario_type == "data_center_demand_spike"
    assert any("Added DC_A at downstream bus 32" in item for item in state.metadata.modifications)
    assert {data_center.id for data_center in state.data_centers} == {"DC_A", "DC_B"}
    assert state.data_centers[0].zone == "feeder_tail"
    assert state.batteries[0].zone == "feeder_tail"
    assert state.local_generators[0].zone == "feeder_tail"
    assert state.reactive_resources[0].id == "VAR_A"
    assert state.reactive_resources[0].available_mvar == 0.1
    assert any(
        violation.type == "line_overload" and violation.element_id == "line_25"
        for violation in state.violations
    )
    assert any(
        violation.type == "voltage_low" and violation.element_id == "DC_A"
        for violation in state.violations
    )


def test_case33bw_data_center_spike_hard_is_tougher_than_default_spike() -> None:
    easy = load_agent_grid("case33bw_data_center_spike")
    hard = load_agent_grid("case33bw_data_center_spike_hard")

    easy_line_25 = next(line for line in easy.line_loadings if line.line == "line_25")
    hard_line_25 = next(line for line in hard.line_loadings if line.line == "line_25")
    easy_dc_a = next(voltage for voltage in easy.bus_voltages if voltage.bus == "DC_A")
    hard_dc_a = next(voltage for voltage in hard.bus_voltages if voltage.bus == "DC_A")

    assert hard.metadata is not None
    assert hard.metadata.scenario_type == "data_center_demand_spike_hard"
    assert any(
        "Limited DC_A flexible load to 0.25 MW" in item for item in hard.metadata.modifications
    )
    assert hard_line_25.loading_percent > easy_line_25.loading_percent
    assert hard_dc_a.vm_pu < easy_dc_a.vm_pu
    assert hard.data_centers[0].load_mw == 0.75
    assert hard.data_centers[0].flexible_mw == 0.25
    assert hard.batteries[0].available_mw == 0.25
    assert hard.local_generators[0].available_headroom_mw == 0.25


def test_case33bw_data_center_spike_tricky_has_limited_controls() -> None:
    hard = load_agent_grid("case33bw_data_center_spike_hard")
    tricky = load_agent_grid("case33bw_data_center_spike_tricky")

    hard_line_25 = next(line for line in hard.line_loadings if line.line == "line_25")
    tricky_line_25 = next(line for line in tricky.line_loadings if line.line == "line_25")
    hard_dc_a = next(voltage for voltage in hard.bus_voltages if voltage.bus == "DC_A")
    tricky_dc_a = next(voltage for voltage in tricky.bus_voltages if voltage.bus == "DC_A")
    dc_a = next(data_center for data_center in tricky.data_centers if data_center.id == "DC_A")
    dc_b = next(data_center for data_center in tricky.data_centers if data_center.id == "DC_B")

    assert tricky.metadata is not None
    assert tricky.metadata.scenario_type == "data_center_demand_spike_tricky"
    assert any(
        "requiring the planner to choose how much to curtail versus shift" in item
        for item in tricky.metadata.modifications
    )
    assert tricky_line_25.loading_percent > hard_line_25.loading_percent
    assert tricky_dc_a.vm_pu < hard_dc_a.vm_pu
    assert dc_a.load_mw == 0.90
    assert dc_a.flexible_mw == 0.30
    assert round(dc_b.max_load_mw - dc_b.load_mw, 3) == 0.15
    assert tricky.batteries[0].available_mw == 0.20
    assert tricky.local_generators[0].available_headroom_mw == 0.20
    assert tricky.reactive_resources[0].available_mvar == 0.20
