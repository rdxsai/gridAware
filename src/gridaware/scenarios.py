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
    Violation,
)


AgentGridScenario = Literal[
    "mv_data_center_spike",
    "mv_renewable_drop",
    "mv_line_constraint",
    "lv_edge_data_center",
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
class ScenarioBundle:
    scenario_id: AgentGridScenario
    net: pp.pandapowerNet
    data_centers: list[DataCenterSpec]
    grid_state: GridState


def load_agent_grid(scenario_id: AgentGridScenario = "mv_data_center_spike") -> GridState:
    """Build a benchmark pandapower grid variant and return the agent-facing state."""

    return deepcopy(load_agent_scenario(scenario_id).grid_state)


def load_agent_scenario(
    scenario_id: AgentGridScenario = "mv_data_center_spike",
) -> ScenarioBundle:
    """Build a benchmark pandapower grid variant and keep the raw net for simulation."""

    net, data_centers = _build_benchmark_grid(scenario_id)
    pp.runpp(net, numba=False, max_iteration=30)
    grid_state = _grid_state_from_pandapower(net, scenario_id, data_centers)
    return ScenarioBundle(
        scenario_id=scenario_id,
        net=net,
        data_centers=data_centers,
        grid_state=grid_state,
    )


def load_demo_scenario() -> GridState:
    """Return the default benchmark-backed data-center spike scenario."""

    return deepcopy(load_agent_grid("mv_data_center_spike"))


def _build_benchmark_grid(
    scenario_id: AgentGridScenario,
) -> tuple[pp.pandapowerNet, list[DataCenterSpec]]:
    if scenario_id == "lv_edge_data_center":
        return _build_cigre_lv_grid()
    return _build_cigre_mv_grid(scenario_id)


def _build_cigre_mv_grid(
    scenario_id: AgentGridScenario,
) -> tuple[pp.pandapowerNet, list[DataCenterSpec]]:
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

    match scenario_id:
        case "mv_data_center_spike":
            _constrain_line(net, line_index=3, factor=0.35)
        case "mv_renewable_drop":
            net.sgen["p_mw"] *= 0.2
            _constrain_line(net, line_index=3, factor=0.42)
        case "mv_line_constraint":
            _constrain_line(net, line_index=3, factor=0.30)

    return net, data_centers


def _build_cigre_lv_grid() -> tuple[pp.pandapowerNet, list[DataCenterSpec]]:
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
    return net, data_centers


def _grid_state_from_pandapower(
    net: pp.pandapowerNet,
    scenario_id: AgentGridScenario,
    data_center_specs: list[DataCenterSpec],
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
        bus_voltages=bus_voltages,
        line_loadings=line_loadings,
        data_centers=data_centers,
        batteries=[Battery(id="BAT_A", zone="north", available_mw=10.0)],
        local_generators=[LocalGenerator(id="GEN_A", zone="north", available_headroom_mw=12.0)],
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
        BusVoltage(bus=spec.data_center_id, vm_pu=round(float(net.res_bus.at[spec.bus, "vm_pu"]), 3))
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
