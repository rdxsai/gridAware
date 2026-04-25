from __future__ import annotations

from gridaware.models import Action, GridState


def propose_grid_actions(state: GridState, target_violation: str | None = None) -> list[Action]:
    """Return safe, predefined mitigation actions for the demo scenario."""

    stressed_dc = _stressed_data_center(state)
    actions = [
        Action(
            action_id="A1",
            type="shift_data_center_load",
            description="Shift 15 MW of flexible compute load from DC_A to DC_B.",
            parameters={"from_dc": stressed_dc, "to_dc": "DC_B", "mw": 15.0},
            estimated_cost=2.0,
        ),
        Action(
            action_id="A2",
            type="dispatch_battery",
            description="Discharge the 10 MW battery near DC_A.",
            parameters={"battery_id": "BAT_A", "target_dc": stressed_dc, "mw": 10.0},
            estimated_cost=3.0,
        ),
        Action(
            action_id="A3",
            type="increase_local_generation",
            description="Increase local generation near DC_A by 12 MW.",
            parameters={"generator_id": "GEN_A", "target_dc": stressed_dc, "mw": 12.0},
            estimated_cost=4.0,
        ),
        Action(
            action_id="A4",
            type="curtail_flexible_load",
            description="Curtail 8 MW of non-critical flexible load at DC_A.",
            parameters={"dc": stressed_dc, "mw": 8.0},
            estimated_cost=6.0,
        ),
    ]

    if target_violation:
        return actions
    return actions


def get_action_by_id(state: GridState, action_id: str) -> Action:
    for action in propose_grid_actions(state):
        if action.action_id == action_id:
            return action
    raise ValueError(f"Unknown action_id: {action_id}")


def _stressed_data_center(state: GridState) -> str:
    low_voltage = min(state.bus_voltages, key=lambda voltage: voltage.vm_pu)
    return low_voltage.bus if low_voltage.bus.startswith("DC_") else "DC_A"
