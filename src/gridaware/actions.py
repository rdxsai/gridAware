from __future__ import annotations

from gridaware.models import Action, ActionIntent, ActionValidation, GridState


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


def action_to_intent(action: Action) -> ActionIntent:
    params = action.parameters
    return ActionIntent(
        type=action.type,
        from_dc=_string_param(params, "from_dc"),
        to_dc=_string_param(params, "to_dc"),
        battery_id=_string_param(params, "battery_id"),
        generator_id=_string_param(params, "generator_id"),
        target_dc=_string_param(params, "target_dc"),
        dc=_string_param(params, "dc"),
        mw=float(params["mw"]),
    )


def validate_action_intent(
    state: GridState,
    intent: ActionIntent,
    action_id: str = "agent_intent",
) -> ActionValidation:
    match intent.type:
        case "shift_data_center_load":
            return _validate_shift_load(state, intent, action_id)
        case "dispatch_battery":
            return _validate_dispatch_battery(state, intent, action_id)
        case "increase_local_generation":
            return _validate_increase_generation(state, intent, action_id)
        case "curtail_flexible_load":
            return _validate_curtail_load(state, intent, action_id)


def validate_action(state: GridState, action: Action) -> ActionValidation:
    return validate_action_intent(state, action_to_intent(action), action.action_id)


def _stressed_data_center(state: GridState) -> str:
    low_voltage = min(state.bus_voltages, key=lambda voltage: voltage.vm_pu)
    return low_voltage.bus if low_voltage.bus.startswith("DC_") else "DC_A"


def _validate_shift_load(state: GridState, intent: ActionIntent, action_id: str) -> ActionValidation:
    if not intent.from_dc or not intent.to_dc:
        return _invalid("shift_data_center_load requires from_dc and to_dc")
    if intent.from_dc == intent.to_dc:
        return _invalid("from_dc and to_dc must be different")

    source = _data_center(state, intent.from_dc)
    target = _data_center(state, intent.to_dc)
    if source is None:
        return _invalid(f"Unknown source data center: {intent.from_dc}")
    if target is None:
        return _invalid(f"Unknown target data center: {intent.to_dc}")
    if intent.mw <= 0:
        return _invalid("mw must be greater than zero")
    if intent.mw > source.flexible_mw:
        return _invalid(f"{source.id} has only {source.flexible_mw} MW flexible load")
    if target.load_mw + intent.mw > target.max_load_mw:
        return _invalid(f"{target.id} would exceed max load {target.max_load_mw} MW")

    return _valid(
        Action(
            action_id=action_id,
            type=intent.type,
            description=f"Shift {intent.mw:g} MW of flexible load from {source.id} to {target.id}.",
            parameters={"from_dc": source.id, "to_dc": target.id, "mw": intent.mw},
            estimated_cost=2.0,
        )
    )


def _validate_dispatch_battery(state: GridState, intent: ActionIntent, action_id: str) -> ActionValidation:
    if not intent.battery_id or not intent.target_dc:
        return _invalid("dispatch_battery requires battery_id and target_dc")

    battery = next((item for item in state.batteries if item.id == intent.battery_id), None)
    target = _data_center(state, intent.target_dc)
    if battery is None:
        return _invalid(f"Unknown battery: {intent.battery_id}")
    if target is None:
        return _invalid(f"Unknown target data center: {intent.target_dc}")
    if intent.mw <= 0:
        return _invalid("mw must be greater than zero")
    if intent.mw > battery.available_mw:
        return _invalid(f"{battery.id} has only {battery.available_mw} MW available")

    return _valid(
        Action(
            action_id=action_id,
            type=intent.type,
            description=f"Dispatch {intent.mw:g} MW from {battery.id} near {target.id}.",
            parameters={"battery_id": battery.id, "target_dc": target.id, "mw": intent.mw},
            estimated_cost=3.0,
        )
    )


def _validate_increase_generation(
    state: GridState, intent: ActionIntent, action_id: str
) -> ActionValidation:
    if not intent.generator_id or not intent.target_dc:
        return _invalid("increase_local_generation requires generator_id and target_dc")

    generator = next(
        (item for item in state.local_generators if item.id == intent.generator_id), None
    )
    target = _data_center(state, intent.target_dc)
    if generator is None:
        return _invalid(f"Unknown local generator: {intent.generator_id}")
    if target is None:
        return _invalid(f"Unknown target data center: {intent.target_dc}")
    if intent.mw <= 0:
        return _invalid("mw must be greater than zero")
    if intent.mw > generator.available_headroom_mw:
        return _invalid(f"{generator.id} has only {generator.available_headroom_mw} MW headroom")

    return _valid(
        Action(
            action_id=action_id,
            type=intent.type,
            description=f"Increase {generator.id} output by {intent.mw:g} MW near {target.id}.",
            parameters={"generator_id": generator.id, "target_dc": target.id, "mw": intent.mw},
            estimated_cost=4.0,
        )
    )


def _validate_curtail_load(state: GridState, intent: ActionIntent, action_id: str) -> ActionValidation:
    if not intent.dc:
        return _invalid("curtail_flexible_load requires dc")

    dc = _data_center(state, intent.dc)
    if dc is None:
        return _invalid(f"Unknown data center: {intent.dc}")
    if intent.mw <= 0:
        return _invalid("mw must be greater than zero")
    if intent.mw > dc.flexible_mw:
        return _invalid(f"{dc.id} has only {dc.flexible_mw} MW flexible load")

    return _valid(
        Action(
            action_id=action_id,
            type=intent.type,
            description=f"Curtail {intent.mw:g} MW of flexible load at {dc.id}.",
            parameters={"dc": dc.id, "mw": intent.mw},
            estimated_cost=6.0,
        )
    )


def _data_center(state: GridState, data_center_id: str):
    return next((dc for dc in state.data_centers if dc.id == data_center_id), None)


def _string_param(params: dict[str, str | float], key: str) -> str | None:
    value = params.get(key)
    return value if isinstance(value, str) else None


def _valid(action: Action) -> ActionValidation:
    return ActionValidation(valid=True, reason="Action is feasible for the current grid state.", action=action)


def _invalid(reason: str) -> ActionValidation:
    return ActionValidation(valid=False, reason=reason)
