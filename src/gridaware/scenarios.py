from __future__ import annotations

from copy import deepcopy

from gridaware.models import (
    Battery,
    BusVoltage,
    DataCenterLoad,
    GridState,
    LineLoading,
    LocalGenerator,
    Violation,
)


def load_demo_scenario() -> GridState:
    """Return the default data-center demand spike scenario."""

    return deepcopy(
        GridState(
            scenario_id="dc_spike_001",
            bus_voltages=[
                BusVoltage(bus="SUBSTATION", vm_pu=1.01),
                BusVoltage(bus="DC_A", vm_pu=0.93),
                BusVoltage(bus="DC_B", vm_pu=0.98),
            ],
            line_loadings=[
                LineLoading(line="line_1", loading_percent=72.0),
                LineLoading(line="line_4", loading_percent=118.5),
                LineLoading(line="line_7", loading_percent=86.0),
            ],
            data_centers=[
                DataCenterLoad(
                    id="DC_A",
                    zone="north",
                    load_mw=80.0,
                    flexible_mw=24.0,
                    max_load_mw=95.0,
                ),
                DataCenterLoad(
                    id="DC_B",
                    zone="south",
                    load_mw=42.0,
                    flexible_mw=18.0,
                    max_load_mw=65.0,
                ),
            ],
            batteries=[Battery(id="BAT_A", zone="north", available_mw=10.0)],
            local_generators=[
                LocalGenerator(id="GEN_A", zone="north", available_headroom_mw=12.0)
            ],
            violations=[
                Violation(
                    type="line_overload",
                    element_id="line_4",
                    observed=118.5,
                    limit=100.0,
                    units="percent",
                ),
                Violation(
                    type="voltage_low",
                    element_id="DC_A",
                    observed=0.93,
                    limit=0.95,
                    units="pu",
                ),
            ],
            grid_health_score=62,
        )
    )
