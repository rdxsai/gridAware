from fastapi.testclient import TestClient

from gridaware.api import app
from gridaware.topology import build_current_topology_view


def test_current_topology_view_contains_clickable_assets_and_overloaded_line() -> None:
    view = build_current_topology_view("case33bw_data_center_spike_tricky")

    assert view.scenario_id == "case33bw_data_center_spike_tricky"
    assert view.metrics["grid_health"] == 0
    assert view.metrics["active_violations"] == 2
    assert len(view.nodes) == 13
    assert len(view.edges) == 12

    dc_a = next(node for node in view.nodes if node.id == "DC_A")
    assert dc_a.kind == "data_center"
    assert dc_a.bus == "Bus 12"
    assert dc_a.status == "normal"
    assert dc_a.details["load_mw"] == 0.9
    assert dc_a.details["voltage_pu"] == 0.904

    line_25 = next(edge for edge in view.edges if edge.id == "line_25")
    assert line_25.from_node == "bus_4"
    assert line_25.to_node == "bus_8"
    assert line_25.status == "normal"
    assert line_25.loading_percent == 147.4
    assert line_25.details["from"] == "Bus 4"
    assert line_25.details["to"] == "Bus 8"
    assert line_25.details["line_type"] == "OH"
    assert line_25.details["route"] == [{"x": 290, "y": 290}, {"x": 290, "y": 505}]

    bus_10_to_12 = next(edge for edge in view.edges if edge.id == "line_display_11")
    assert bus_10_to_12.details["route"] == [
        {"x": 290, "y": 655},
        {"x": 235, "y": 655},
        {"x": 235, "y": 775},
    ]


def test_topology_api_and_static_app_are_served() -> None:
    client = TestClient(app)

    topology_response = client.get("/grid/topology/current")
    app_response = client.get("/app")
    root_response = client.get("/")
    css_response = client.get("/static/topology.css")

    assert topology_response.status_code == 200
    assert topology_response.json()["scenario_id"] == "case33bw_data_center_spike_tricky"
    assert app_response.status_code == 200
    assert "gridAware Topology" in app_response.text
    assert "topology-stage" in app_response.text
    assert "edge-layer" in app_response.text
    assert "topology.js?v=20260426-r23" in app_response.text
    assert root_response.status_code == 200
    assert "gridAware Topology" in root_response.text
    assert css_response.status_code == 200
    assert ".edge-segment" in css_response.text
