from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from gridaware.scenarios import AgentGridScenario, ScenarioBundle, load_agent_scenario


TopologyNodeKind = Literal[
    "slack",
    "bus",
    "data_center",
    "battery",
    "generator",
    "reactive_support",
]
TopologyStatus = Literal["normal", "warning", "violation", "overloaded"]


class TopologyNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: TopologyNodeKind
    label: str
    bus: str
    x: float
    y: float
    status: TopologyStatus
    details: dict[str, Any]


class TopologyEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    from_node: str
    to_node: str
    label: str
    status: TopologyStatus
    loading_percent: float | None
    details: dict[str, Any]


class CurrentTopologyView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    view_mode: Literal["current"]
    layout: Literal["radial"]
    generated_at: str
    metrics: dict[str, Any]
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]


BUS_COORDINATES = {
    "bus_1": (70, 160),
    "bus_2": (290, 160),
    "bus_3": (490, 160),
    "bus_4": (290, 290),
    "bus_5": (480, 290),
    "bus_6": (635, 290),
    "bus_7": (790, 290),
    "bus_8": (290, 505),
    "bus_9": (400, 405),
    "bus_10": (290, 655),
    "bus_11": (480, 655),
    "bus_12": (235, 775),
    "bus_13": (680, 775),
}

DISPLAY_BUS_TO_PP_INDEX = {
    "bus_1": 0,
    "bus_2": 1,
    "bus_3": 2,
    "bus_4": 3,
    "bus_5": 4,
    "bus_6": 5,
    "bus_7": 6,
    "bus_8": 7,
    "bus_9": 8,
    "bus_10": 9,
    "bus_11": 10,
    "bus_12": 32,
    "bus_13": 21,
}

DISPLAY_EDGES = [
    ("line_display_1", "bus_1", "bus_2", ["bus_1", "bus_2"]),
    ("line_display_2", "bus_2", "bus_3", ["bus_2", "bus_3"]),
    ("line_display_3", "bus_2", "bus_4", ["bus_2", "bus_4"]),
    ("line_display_4", "bus_4", "bus_5", ["bus_4", "bus_5"]),
    ("line_display_5", "bus_5", "bus_6", ["bus_5", "bus_6"]),
    ("line_display_6", "bus_6", "bus_7", ["bus_6", "bus_7"]),
    ("line_25", "bus_4", "bus_8", ["bus_4", "bus_8"]),
    ("line_display_8", "bus_4", "bus_9", ["bus_4", "junction_4_9", "bus_9"]),
    ("line_display_9", "bus_8", "bus_10", ["bus_8", "bus_10"]),
    ("line_display_10", "bus_10", "bus_11", ["bus_10", "bus_11"]),
    ("line_display_11", "bus_10", "bus_12", ["bus_10", "junction_10_12", "bus_12"]),
    ("line_display_12", "bus_11", "bus_13", ["bus_11", "junction_11_13", "bus_13"]),
]

ROUTE_POINTS = {
    **BUS_COORDINATES,
    "junction_4_9": (400, 290),
    "junction_10_12": (235, 655),
    "junction_11_13": (680, 655),
}


def build_current_topology_view(
    scenario_id: AgentGridScenario = "case33bw_data_center_spike_tricky",
) -> CurrentTopologyView:
    bundle = load_agent_scenario(scenario_id)
    return build_topology_view_from_bundle(bundle, scenario_id)


def build_topology_view_from_bundle(
    bundle: ScenarioBundle,
    scenario_id: AgentGridScenario,
) -> CurrentTopologyView:
    generated_at = datetime.now().strftime("%I:%M:%S %p").lstrip("0")
    return CurrentTopologyView(
        scenario_id=scenario_id,
        view_mode="current",
        layout="radial",
        generated_at=generated_at,
        metrics={
            "grid_health": bundle.grid_state.grid_health_score,
            "active_violations": len(bundle.grid_state.violations),
            "voltage_low_limit_pu": 0.95,
            "line_loading_limit_percent": 100.0,
        },
        nodes=_topology_nodes(bundle),
        edges=_topology_edges(bundle, generated_at),
    )


def _topology_nodes(bundle: ScenarioBundle) -> list[TopologyNode]:
    voltages = {
        display_id: round(float(bundle.net.res_bus.at[pp_index, "vm_pu"]), 3)
        for display_id, pp_index in DISPLAY_BUS_TO_PP_INDEX.items()
    }
    nodes = [
        _node("bus_1", "slack", "SLACK", "Bus 1", "normal", {"role": "reference source"}, voltages),
        _node("bus_2", "bus", "Bus 2", "Bus 2", "normal", {}, voltages),
        _asset_node("GEN_A", "generator", "GEN_A", "Bus 3", "bus_3", bundle),
        _node("bus_4", "bus", "Bus 4", "Bus 4", "normal", {}, voltages),
        _node("bus_5", "bus", "Bus 5", "Bus 5", "normal", {}, voltages),
        _node("bus_6", "bus", "Bus 6", "Bus 6", "normal", {}, voltages),
        _asset_node("VAR_A", "reactive_support", "VAR_A", "Bus 7", "bus_7", bundle),
        _asset_node("BAT_A", "battery", "BAT_A", "Bus 8", "bus_8", bundle),
        _node("bus_9", "bus", "Bus 9", "Bus 9", "normal", {}, voltages),
        _node("bus_10", "bus", "Bus 10", "Bus 10", "normal", {}, voltages),
        _node("bus_11", "bus", "Bus 11", "Bus 11", "normal", {}, voltages),
        _data_center_node("DC_A", "Bus 12", "bus_12", bundle),
        _data_center_node("DC_B", "Bus 13", "bus_13", bundle),
    ]
    return nodes


def _topology_edges(bundle: ScenarioBundle, generated_at: str) -> list[TopologyEdge]:
    return [
        _line_25_edge(bundle, route, generated_at)
        if edge_id == "line_25"
        else _display_edge(edge_id, from_node, to_node, route)
        for edge_id, from_node, to_node, route in DISPLAY_EDGES
    ]


def _node(
    node_id: str,
    kind: TopologyNodeKind,
    label: str,
    bus: str,
    status: TopologyStatus,
    details: dict[str, Any],
    voltages: dict[str, float] | None = None,
) -> TopologyNode:
    x, y = BUS_COORDINATES[node_id]
    voltage_pu = voltages.get(node_id) if voltages else None
    enriched = {**details}
    if voltage_pu is not None:
        enriched["voltage_pu"] = round(float(voltage_pu), 3)
    return TopologyNode(
        id=node_id,
        kind=kind,
        label=label,
        bus=bus,
        x=x,
        y=y,
        status="normal",
        details=enriched,
    )


def _asset_node(
    node_id: str,
    kind: TopologyNodeKind,
    label: str,
    bus: str,
    coordinate_key: str,
    bundle: ScenarioBundle,
) -> TopologyNode:
    x, y = BUS_COORDINATES[coordinate_key]
    details: dict[str, Any]
    if node_id == "BAT_A":
        battery = next(item for item in bundle.grid_state.batteries if item.id == node_id)
        details = {"available_mw": battery.available_mw, "zone": battery.zone}
    elif node_id == "GEN_A":
        generator = next(item for item in bundle.grid_state.local_generators if item.id == node_id)
        details = {"headroom_mw": generator.available_headroom_mw, "zone": generator.zone}
    else:
        resource = next(item for item in bundle.grid_state.reactive_resources if item.id == node_id)
        details = {"available_mvar": resource.available_mvar, "zone": resource.zone}
    return TopologyNode(
        id=node_id,
        kind=kind,
        label=label,
        bus=bus,
        x=x,
        y=y,
        status="normal",
        details=details,
    )


def _data_center_node(
    data_center_id: str,
    bus: str,
    coordinate_key: str,
    bundle: ScenarioBundle,
) -> TopologyNode:
    data_center = next(item for item in bundle.grid_state.data_centers if item.id == data_center_id)
    voltage = next(
        item.vm_pu for item in bundle.grid_state.bus_voltages if item.bus == data_center_id
    )
    x, y = BUS_COORDINATES[coordinate_key]
    return TopologyNode(
        id=data_center_id,
        kind="data_center",
        label=data_center_id,
        bus=bus,
        x=x,
        y=y,
        status="normal",
        details={
            "load_mw": data_center.load_mw,
            "voltage_pu": voltage,
            "flexible_mw": data_center.flexible_mw,
            "max_load_mw": data_center.max_load_mw,
            "zone": data_center.zone,
        },
    )


def _display_edge(edge_id: str, from_node: str, to_node: str, route: list[str]) -> TopologyEdge:
    return TopologyEdge(
        id=edge_id,
        from_node=from_node,
        to_node=to_node,
        label="",
        status="normal",
        loading_percent=None,
        details={
            "from": _bus_label(from_node),
            "to": _bus_label(to_node),
            "route": _route_coordinates(route),
        },
    )


def _line_25_edge(bundle: ScenarioBundle, route: list[str], generated_at: str) -> TopologyEdge:
    line_index = 24
    line = bundle.net.line.loc[line_index]
    result = bundle.net.res_line.loc[line_index]
    loading_percent = round(float(result.loading_percent), 1)
    current_ka = round(float(result.i_ka), 3)
    limit_ka = round(float(line.max_i_ka), 3)
    details = {
        "from": "Bus 4",
        "to": "Bus 8",
        "loading_percent": loading_percent,
        "current_ka": current_ka,
        "limit_ka": limit_ka,
        "power_flow_mw": round(abs(float(result.p_from_mw)), 2),
        "loss_mw": round(float(result.pl_mw), 2),
        "length_km": round(float(line.length_km), 2),
        "line_type": _line_type(line),
        "last_updated": generated_at,
        "route": _route_coordinates(route),
    }
    return TopologyEdge(
        id="line_25",
        from_node="bus_4",
        to_node="bus_8",
        label="line_25",
        status="normal",
        loading_percent=loading_percent,
        details=details,
    )


def _line_type(line: Any) -> str:
    std_type = str(getattr(line, "std_type", "") or "")
    if "cable" in std_type.lower():
        return "UG"
    return "OH"


def _route_coordinates(route: list[str]) -> list[dict[str, float]]:
    return [{"x": ROUTE_POINTS[item][0], "y": ROUTE_POINTS[item][1]} for item in route]


def _bus_label(node_id: str) -> str:
    return "Bus " + node_id.rsplit("_", 1)[-1]
