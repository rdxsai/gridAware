from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

import pandapower as pp
import pandapower.networks as pn

from gridaware.models import (
    Battery,
    BusVoltage,
    DataCenterLoad,
    GridState,
    LineLoading,
    LocalGenerator,
    ReactiveResource,
    ScenarioMetadata,
    Violation,
)


AgentGridScenario = Literal[
    "baseline_case33bw",
    "case33bw_data_center_spike",
    "case33bw_data_center_spike_hard",
    "mv_data_center_spike",
    "mv_renewable_drop",
    "mv_line_constraint",
    "lv_edge_data_center",
]

ALLOWED_DATA_CENTER_ACTIONS = [
    "shift_data_center_load",
    "dispatch_battery",
    "increase_local_generation",
    "curtail_flexible_load",
]

ALLOWED_DATA_CENTER_VOLTAGE_ACTIONS = [
    *ALLOWED_DATA_CENTER_ACTIONS,
    "adjust_reactive_support",
]


@dataclass
class DataCenterSpec:
    data_center_id: str
    bus: int
    zone: str
    pp_load_mw: float
    pp_q_mvar: float
    display_load_mw: float
    flexible_mw: float
    max_load_mw: float
    load_index: int | None = None

    @property
    def pp_mw_per_display_mw(self) -> float:
        return self.pp_load_mw / self.display_load_mw

    @property
    def pp_q_mvar_per_display_mw(self) -> float:
        return self.pp_q_mvar / self.display_load_mw


@dataclass
class ReactiveSupportSpec:
    resource_id: str
    bus: int
    zone: str
    available_mvar: float


@dataclass
class ScenarioBundle:
    scenario_id: AgentGridScenario
    net: pp.pandapowerNet
    data_centers: list[DataCenterSpec]
    batteries: list[Battery]
    local_generators: list[LocalGenerator]
    reactive_resources: list[ReactiveSupportSpec]
    allowed_action_types: list[str]
    metadata: ScenarioMetadata
    grid_state: GridState


def load_agent_grid(scenario_id: AgentGridScenario = "mv_data_center_spike") -> GridState:
    """Build a benchmark pandapower grid variant and return the agent-facing state."""

    return deepcopy(load_agent_scenario(scenario_id).grid_state)


def load_agent_scenario(
    scenario_id: AgentGridScenario = "mv_data_center_spike",
) -> ScenarioBundle:
    """Build a benchmark pandapower grid variant and keep the raw net for simulation."""

    (
        net,
        data_centers,
        batteries,
        local_generators,
        reactive_resources,
        allowed_actions,
        metadata,
    ) = _build_benchmark_grid(scenario_id)
    pp.runpp(net, numba=False, max_iteration=30)
    grid_state = _grid_state_from_pandapower(
        net,
        scenario_id,
        data_centers,
        batteries,
        local_generators,
        reactive_resources,
        metadata,
    )
    return ScenarioBundle(
        scenario_id=scenario_id,
        net=net,
        data_centers=data_centers,
        batteries=batteries,
        local_generators=local_generators,
        reactive_resources=reactive_resources,
        allowed_action_types=allowed_actions,
        metadata=metadata,
        grid_state=grid_state,
    )


def load_demo_scenario() -> GridState:
    """Return the default benchmark-backed data-center spike scenario."""

    return deepcopy(load_agent_grid("mv_data_center_spike"))


def _build_benchmark_grid(
    scenario_id: AgentGridScenario,
) -> tuple[
    pp.pandapowerNet,
    list[DataCenterSpec],
    list[Battery],
    list[LocalGenerator],
    list[ReactiveSupportSpec],
    list[str],
    ScenarioMetadata,
]:
    if scenario_id == "baseline_case33bw":
        return _build_case33bw_baseline()
    if scenario_id == "case33bw_data_center_spike":
        return _build_case33bw_data_center_spike()
    if scenario_id == "case33bw_data_center_spike_hard":
        return _build_case33bw_data_center_spike_hard()
    if scenario_id == "lv_edge_data_center":
        return _build_cigre_lv_grid()
    return _build_cigre_mv_grid(scenario_id)


def _build_case33bw_baseline() -> tuple[
    pp.pandapowerNet,
    list[DataCenterSpec],
    list[Battery],
    list[LocalGenerator],
    list[ReactiveSupportSpec],
    list[str],
    ScenarioMetadata,
]:
    net = pn.case33bw()
    metadata = ScenarioMetadata(
        scenario_id="baseline_case33bw",
        base_network="pandapower.networks.case33bw()",
        scenario_type="untouched_benchmark",
        purpose="Preserve the original case33bw benchmark for comparison against modified scenarios.",
        modifications=[
            "No modifications. This scenario loads pandapower.networks.case33bw() as-is."
        ],
        limitations=[
            "The benchmark is a synthetic test feeder, not a real utility feeder.",
            "The original case33bw ampacity values are not calibrated for line-overload demos.",
        ],
    )
    return net, [], [], [], [], [], metadata


def _build_case33bw_data_center_spike() -> tuple[
    pp.pandapowerNet,
    list[DataCenterSpec],
    list[Battery],
    list[LocalGenerator],
    list[ReactiveSupportSpec],
    list[str],
    ScenarioMetadata,
]:
    net = pn.case33bw()
    net.ext_grid.at[0, "vm_pu"] = 1.04
    net.line.loc[net.line.in_service, "max_i_ka"] = 0.40

    data_centers = [
        DataCenterSpec(
            data_center_id="DC_A",
            bus=32,
            zone="feeder_tail",
            pp_load_mw=0.50,
            pp_q_mvar=0.175,
            display_load_mw=0.50,
            flexible_mw=0.50,
            max_load_mw=0.70,
        ),
        DataCenterSpec(
            data_center_id="DC_B",
            bus=21,
            zone="mid_feeder",
            pp_load_mw=0.25,
            pp_q_mvar=0.08,
            display_load_mw=0.25,
            flexible_mw=0.10,
            max_load_mw=0.80,
        ),
    ]

    for data_center in data_centers:
        data_center.load_index = pp.create_load(
            net,
            bus=data_center.bus,
            p_mw=data_center.pp_load_mw,
            q_mvar=data_center.pp_q_mvar,
            name=data_center.data_center_id,
        )

    net.line.at[24, "max_i_ka"] = 0.08
    metadata = ScenarioMetadata(
        scenario_id="case33bw_data_center_spike",
        base_network="pandapower.networks.case33bw()",
        scenario_type="data_center_demand_spike",
        purpose=(
            "Test mitigation under downstream data-center load stress on a radial "
            "distribution feeder."
        ),
        modifications=[
            "Started from pandapower.networks.case33bw().",
            "Set the substation voltage setpoint to 1.04 pu to represent normal feeder voltage support before the spike.",
            "Set active feeder line ampacity to 0.40 kA because the benchmark default ampacity is not calibrated for operational loading comparisons.",
            "Added DC_A at downstream bus 32 with 0.50 MW / 0.175 MVAr demand.",
            "Added DC_B at mid-feeder bus 21 with 0.25 MW / 0.08 MVAr demand and 0.55 MW receiving headroom.",
            "Added BAT_A in the feeder_tail zone with 0.50 MW available.",
            "Added GEN_A in the feeder_tail zone with 0.50 MW available headroom.",
            "Added VAR_A in the feeder_tail zone with 0.10 MVAr reactive support available.",
            "Set line_25 ampacity to 0.08 kA to represent a constrained upstream feeder corridor.",
        ],
        limitations=[
            "Benchmark-based synthetic scenario, not a real utility feeder.",
            "Data-center and flexibility assets are synthetic additions.",
            "The constrained corridor is documented scenario stress, not an inferred real-world asset rating.",
        ],
    )
    return (
        net,
        data_centers,
        [Battery(id="BAT_A", zone="feeder_tail", available_mw=0.50)],
        [LocalGenerator(id="GEN_A", zone="feeder_tail", available_headroom_mw=0.50)],
        [ReactiveSupportSpec(resource_id="VAR_A", bus=32, zone="feeder_tail", available_mvar=0.10)],
        ALLOWED_DATA_CENTER_VOLTAGE_ACTIONS.copy(),
        metadata,
    )


def _build_case33bw_data_center_spike_hard() -> tuple[
    pp.pandapowerNet,
    list[DataCenterSpec],
    list[Battery],
    list[LocalGenerator],
    list[ReactiveSupportSpec],
    list[str],
    ScenarioMetadata,
]:
    net = pn.case33bw()
    net.ext_grid.at[0, "vm_pu"] = 1.04
    net.line.loc[net.line.in_service, "max_i_ka"] = 0.40

    data_centers = [
        DataCenterSpec(
            data_center_id="DC_A",
            bus=32,
            zone="feeder_tail",
            pp_load_mw=0.75,
            pp_q_mvar=0.2625,
            display_load_mw=0.75,
            flexible_mw=0.25,
            max_load_mw=0.90,
        ),
        DataCenterSpec(
            data_center_id="DC_B",
            bus=21,
            zone="mid_feeder",
            pp_load_mw=0.35,
            pp_q_mvar=0.112,
            display_load_mw=0.35,
            flexible_mw=0.10,
            max_load_mw=0.70,
        ),
    ]

    for data_center in data_centers:
        data_center.load_index = pp.create_load(
            net,
            bus=data_center.bus,
            p_mw=data_center.pp_load_mw,
            q_mvar=data_center.pp_q_mvar,
            name=data_center.data_center_id,
        )

    net.line.at[24, "max_i_ka"] = 0.08
    metadata = ScenarioMetadata(
        scenario_id="case33bw_data_center_spike_hard",
        base_network="pandapower.networks.case33bw()",
        scenario_type="data_center_demand_spike_hard",
        purpose=(
            "Stress-test the current single-action agent loop under a tougher downstream "
            "data-center load condition."
        ),
        modifications=[
            "Started from pandapower.networks.case33bw().",
            "Set the substation voltage setpoint to 1.04 pu to represent normal feeder voltage support before the spike.",
            "Set active feeder line ampacity to 0.40 kA because the benchmark default ampacity is not calibrated for operational loading comparisons.",
            "Added DC_A at downstream bus 32 with 0.75 MW / 0.2625 MVAr demand.",
            "Limited DC_A flexible load to 0.25 MW so one curtailment action cannot remove the full data-center demand.",
            "Added DC_B at mid-feeder bus 21 with 0.35 MW / 0.112 MVAr demand and 0.35 MW receiving headroom.",
            "Added BAT_A in the feeder_tail zone with 0.25 MW available.",
            "Added GEN_A in the feeder_tail zone with 0.25 MW available headroom.",
            "Added VAR_A in the feeder_tail zone with 0.10 MVAr reactive support available.",
            "Set line_25 ampacity to 0.08 kA to represent a constrained upstream feeder corridor.",
        ],
        limitations=[
            "Benchmark-based synthetic scenario, not a real utility feeder.",
            "Data-center and flexibility assets are synthetic additions.",
            "This variant is intentionally harder and may require cumulative actions, which the current simulator does not yet optimize.",
        ],
    )
    return (
        net,
        data_centers,
        [Battery(id="BAT_A", zone="feeder_tail", available_mw=0.25)],
        [LocalGenerator(id="GEN_A", zone="feeder_tail", available_headroom_mw=0.25)],
        [ReactiveSupportSpec(resource_id="VAR_A", bus=32, zone="feeder_tail", available_mvar=0.10)],
        ALLOWED_DATA_CENTER_VOLTAGE_ACTIONS.copy(),
        metadata,
    )


def _build_cigre_mv_grid(
    scenario_id: AgentGridScenario,
) -> tuple[
    pp.pandapowerNet,
    list[DataCenterSpec],
    list[Battery],
    list[LocalGenerator],
    list[ReactiveSupportSpec],
    list[str],
    ScenarioMetadata,
]:
    net = pn.create_cigre_network_mv(with_der="all")
    data_centers = [
        DataCenterSpec(
            data_center_id="DC_A",
            bus=11,
            zone="north",
            pp_load_mw=1.0,
            pp_q_mvar=0.30,
            display_load_mw=80.0,
            flexible_mw=24.0,
            max_load_mw=95.0,
        ),
        DataCenterSpec(
            data_center_id="DC_B",
            bus=1,
            zone="south",
            pp_load_mw=0.8,
            pp_q_mvar=0.24,
            display_load_mw=42.0,
            flexible_mw=18.0,
            max_load_mw=65.0,
        ),
    ]

    for data_center in data_centers:
        data_center.load_index = pp.create_load(
            net,
            bus=data_center.bus,
            p_mw=data_center.pp_load_mw,
            q_mvar=data_center.pp_q_mvar,
            name=data_center.data_center_id,
        )

    metadata = ScenarioMetadata(
        scenario_id=scenario_id,
        base_network="pandapower.networks.create_cigre_network_mv(with_der='all')",
        scenario_type="data_center_distribution_stress",
        purpose="Benchmark-backed MV scenario for testing data-center load mitigation actions.",
        modifications=[
            "Started from the CIGRE MV reference network with DER enabled.",
            "Added DC_A at bus 11 and DC_B at bus 1 as synthetic flexible data-center loads.",
            "Added BAT_A and GEN_A as synthetic controllable resources in the north zone.",
        ],
        limitations=[
            "Benchmark-based synthetic scenario, not a real utility feeder.",
            "Data-center and flexibility assets are synthetic additions.",
        ],
    )

    match scenario_id:
        case "mv_data_center_spike":
            _constrain_line(net, line_index=3, factor=0.35)
            metadata.modifications.append(
                "Derated line_4 to 35% of its benchmark ampacity to represent a constrained corridor."
            )
        case "mv_renewable_drop":
            net.sgen["p_mw"] *= 0.2
            _constrain_line(net, line_index=3, factor=0.42)
            metadata.modifications.extend(
                [
                    "Reduced benchmark DER active output to 20% to represent a renewable drop.",
                    "Derated line_4 to 42% of its benchmark ampacity to represent a constrained corridor.",
                ]
            )
        case "mv_line_constraint":
            _constrain_line(net, line_index=3, factor=0.30)
            metadata.modifications.append(
                "Derated line_4 to 30% of its benchmark ampacity to represent a tighter line constraint."
            )

    return (
        net,
        data_centers,
        [Battery(id="BAT_A", zone="north", available_mw=10.0)],
        [LocalGenerator(id="GEN_A", zone="north", available_headroom_mw=12.0)],
        [],
        ALLOWED_DATA_CENTER_ACTIONS.copy(),
        metadata,
    )


def _build_cigre_lv_grid() -> tuple[
    pp.pandapowerNet,
    list[DataCenterSpec],
    list[Battery],
    list[LocalGenerator],
    list[ReactiveSupportSpec],
    list[str],
    ScenarioMetadata,
]:
    net = pn.create_cigre_network_lv()
    data_centers = [
        DataCenterSpec(
            data_center_id="DC_A",
            bus=43,
            zone="edge",
            pp_load_mw=0.05,
            pp_q_mvar=0.015,
            display_load_mw=8.0,
            flexible_mw=3.0,
            max_load_mw=10.0,
        ),
        DataCenterSpec(
            data_center_id="DC_B",
            bus=24,
            zone="commercial",
            pp_load_mw=0.03,
            pp_q_mvar=0.009,
            display_load_mw=4.0,
            flexible_mw=2.0,
            max_load_mw=6.0,
        ),
    ]

    for data_center in data_centers:
        data_center.load_index = pp.create_load(
            net,
            bus=data_center.bus,
            p_mw=data_center.pp_load_mw,
            q_mvar=data_center.pp_q_mvar,
            name=data_center.data_center_id,
        )

    _constrain_line(net, line_index=23, factor=0.10)
    metadata = ScenarioMetadata(
        scenario_id="lv_edge_data_center",
        base_network="pandapower.networks.create_cigre_network_lv()",
        scenario_type="edge_data_center_stress",
        purpose="Benchmark-backed LV scenario for testing edge data-center mitigation actions.",
        modifications=[
            "Started from the CIGRE LV reference network.",
            "Added DC_A at bus 43 and DC_B at bus 24 as synthetic edge data-center loads.",
            "Derated line_24 to 10% of its benchmark ampacity to represent an LV edge constraint.",
            "Added BAT_A and GEN_A as synthetic controllable resources in the edge zone.",
        ],
        limitations=[
            "Benchmark-based synthetic scenario, not a real utility feeder.",
            "Data-center and flexibility assets are synthetic additions.",
        ],
    )
    return (
        net,
        data_centers,
        [Battery(id="BAT_A", zone="edge", available_mw=1.5)],
        [LocalGenerator(id="GEN_A", zone="edge", available_headroom_mw=1.0)],
        [],
        ALLOWED_DATA_CENTER_ACTIONS.copy(),
        metadata,
    )


def _grid_state_from_pandapower(
    net: pp.pandapowerNet,
    scenario_id: AgentGridScenario,
    data_center_specs: list[DataCenterSpec],
    batteries: list[Battery],
    local_generators: list[LocalGenerator],
    reactive_resources: list[ReactiveSupportSpec],
    metadata: ScenarioMetadata,
) -> GridState:
    bus_voltages = _agent_bus_voltages(net, data_center_specs)
    line_loadings = [
        LineLoading(line=f"line_{line_index + 1}", loading_percent=round(row.loading_percent, 1))
        for line_index, row in net.res_line.iterrows()
    ]
    data_centers = [
        DataCenterLoad(
            id=spec.data_center_id,
            zone=spec.zone,
            load_mw=spec.display_load_mw,
            flexible_mw=spec.flexible_mw,
            max_load_mw=spec.max_load_mw,
        )
        for spec in data_center_specs
    ]
    violations = _detect_agent_violations(bus_voltages, line_loadings)

    return GridState(
        scenario_id=scenario_id,
        metadata=metadata,
        bus_voltages=bus_voltages,
        line_loadings=line_loadings,
        data_centers=data_centers,
        batteries=batteries,
        local_generators=local_generators,
        reactive_resources=[
            ReactiveResource(
                id=resource.resource_id,
                zone=resource.zone,
                available_mvar=round(resource.available_mvar, 4),
            )
            for resource in reactive_resources
        ],
        violations=violations,
        grid_health_score=_score_grid(bus_voltages, line_loadings, violations),
    )


def _agent_bus_voltages(
    net: pp.pandapowerNet, data_center_specs: list[DataCenterSpec]
) -> list[BusVoltage]:
    substation_bus = int(net.ext_grid.iloc[0].bus)
    voltages = [
        BusVoltage(bus="SUBSTATION", vm_pu=round(float(net.res_bus.at[substation_bus, "vm_pu"]), 3))
    ]
    voltages.extend(
        BusVoltage(
            bus=spec.data_center_id, vm_pu=round(float(net.res_bus.at[spec.bus, "vm_pu"]), 3)
        )
        for spec in data_center_specs
    )
    return voltages


def _detect_agent_violations(
    bus_voltages: list[BusVoltage], line_loadings: list[LineLoading]
) -> list[Violation]:
    violations: list[Violation] = []
    for line in line_loadings:
        if line.loading_percent > 100.0:
            violations.append(
                Violation(
                    type="line_overload",
                    element_id=line.line,
                    observed=line.loading_percent,
                    limit=100.0,
                    units="percent",
                )
            )

    for voltage in bus_voltages:
        if voltage.vm_pu < 0.95:
            violations.append(
                Violation(
                    type="voltage_low",
                    element_id=voltage.bus,
                    observed=voltage.vm_pu,
                    limit=0.95,
                    units="pu",
                )
            )
        if voltage.vm_pu > 1.05:
            violations.append(
                Violation(
                    type="voltage_high",
                    element_id=voltage.bus,
                    observed=voltage.vm_pu,
                    limit=1.05,
                    units="pu",
                )
            )

    return violations


def _score_grid(
    bus_voltages: list[BusVoltage],
    line_loadings: list[LineLoading],
    violations: list[Violation],
) -> int:
    max_line = max(line.loading_percent for line in line_loadings)
    min_voltage = min(voltage.vm_pu for voltage in bus_voltages)
    line_penalty = max(0.0, max_line - 85.0) * 1.1
    voltage_penalty = max(0.0, 0.98 - min_voltage) * 450.0
    violation_penalty = len(violations) * 8.0
    return round(max(0.0, min(100.0, 100.0 - line_penalty - voltage_penalty - violation_penalty)))


def _constrain_line(net: pp.pandapowerNet, line_index: int, factor: float) -> None:
    net.line.at[line_index, "max_i_ka"] *= factor
