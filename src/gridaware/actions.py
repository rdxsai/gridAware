from __future__ import annotations

from gridaware.models import Action, ActionIntent, ActionIntentValidation, ActionValidation, GridState


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


def validate_action_intent_for_planner(
    state: GridState,
    intent: ActionIntent,
) -> ActionIntentValidation:
    match intent.type:
        case "shift_data_center_load":
            return _validate_shift_load_for_planner(state, intent)
        case "dispatch_battery":
            return _validate_dispatch_battery_for_planner(state, intent)
        case "increase_local_generation":
            return _validate_increase_generation_for_planner(state, intent)
        case "curtail_flexible_load":
            return _validate_curtail_load_for_planner(state, intent)


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


def _validate_shift_load_for_planner(state: GridState, intent: ActionIntent) -> ActionIntentValidation:
    passed: list[str] = []
    failed: list[str] = []
    repair: list[str] = []
    source = _data_center(state, intent.from_dc) if intent.from_dc else None
    target = _data_center(state, intent.to_dc) if intent.to_dc else None

    if source:
        passed.append(f"from_dc exists in data_centers: {source.id}")
    else:
        failed.append(f"from_dc exists in data_centers: {intent.from_dc}")
        repair.append("Choose from_dc from available data_centers.")

    if target:
        passed.append(f"to_dc exists in data_centers: {target.id}")
    else:
        failed.append(f"to_dc exists in data_centers: {intent.to_dc}")
        repair.append("Choose to_dc from available data_centers.")

    if intent.from_dc and intent.to_dc and intent.from_dc != intent.to_dc:
        passed.append(f"from_dc != to_dc: {intent.from_dc} != {intent.to_dc}")
    else:
        failed.append("from_dc != to_dc")
        repair.append("Use different source and destination data centers.")

    if source and intent.mw <= source.flexible_mw:
        passed.append(f"mw <= from_dc.flexible_mw: {intent.mw:g} <= {source.flexible_mw:g}")
    elif source:
        failed.append(f"mw <= from_dc.flexible_mw: {intent.mw:g} > {source.flexible_mw:g}")
        repair.append(f"Reduce mw to <= {source.flexible_mw:g}.")

    if target:
        headroom = target.max_load_mw - target.load_mw
        if intent.mw <= headroom:
            passed.append(f"mw <= to_dc.receiving_headroom_mw: {intent.mw:g} <= {headroom:g}")
        else:
            failed.append(f"mw <= to_dc.receiving_headroom_mw: {intent.mw:g} > {headroom:g}")
            repair.append(f"Reduce mw to <= {headroom:g} or choose another destination.")

    _check_positive_mw(intent, passed, failed, repair)
    normalized = _normalized_shift_intent(source.id, target.id, intent.mw) if not failed and source and target else None
    return _planner_validation(intent, normalized, passed, failed, repair)


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


def _validate_dispatch_battery_for_planner(
    state: GridState, intent: ActionIntent
) -> ActionIntentValidation:
    passed: list[str] = []
    failed: list[str] = []
    repair: list[str] = []
    battery = next((item for item in state.batteries if item.id == intent.battery_id), None)
    target = _data_center(state, intent.target_dc) if intent.target_dc else None

    if battery:
        passed.append(f"battery_id exists in batteries: {battery.id}")
    else:
        failed.append(f"battery_id exists in batteries: {intent.battery_id}")
        repair.append("Choose battery_id from available batteries.")

    if target:
        passed.append(f"target_dc exists in data_centers: {target.id}")
    else:
        failed.append(f"target_dc exists in data_centers: {intent.target_dc}")
        repair.append("Choose target_dc from available data_centers.")

    if battery and intent.mw <= battery.available_mw:
        passed.append(f"mw <= battery.available_mw: {intent.mw:g} <= {battery.available_mw:g}")
    elif battery:
        failed.append(f"mw <= battery.available_mw: {intent.mw:g} > {battery.available_mw:g}")
        repair.append(f"Reduce mw to <= {battery.available_mw:g}.")

    if battery and target and battery.zone == target.zone:
        passed.append(f"battery.zone supports target_dc.zone: {battery.zone} == {target.zone}")
    elif battery and target:
        failed.append(f"battery.zone supports target_dc.zone: {battery.zone} != {target.zone}")
        repair.append("Choose a battery in the target data center zone.")

    _check_positive_mw(intent, passed, failed, repair)
    normalized = (
        _normalized_battery_intent(battery.id, target.id, intent.mw)
        if not failed and battery and target
        else None
    )
    return _planner_validation(intent, normalized, passed, failed, repair)


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


def _validate_increase_generation_for_planner(
    state: GridState, intent: ActionIntent
) -> ActionIntentValidation:
    passed: list[str] = []
    failed: list[str] = []
    repair: list[str] = []
    generator = next(
        (item for item in state.local_generators if item.id == intent.generator_id), None
    )
    target = _data_center(state, intent.target_dc) if intent.target_dc else None

    if generator:
        passed.append(f"generator_id exists in local_generators: {generator.id}")
    else:
        failed.append(f"generator_id exists in local_generators: {intent.generator_id}")
        repair.append("Choose generator_id from available local_generators.")

    if target:
        passed.append(f"target_dc exists in data_centers: {target.id}")
    else:
        failed.append(f"target_dc exists in data_centers: {intent.target_dc}")
        repair.append("Choose target_dc from available data_centers.")

    if generator and intent.mw <= generator.available_headroom_mw:
        passed.append(
            f"mw <= generator.available_headroom_mw: {intent.mw:g} <= "
            f"{generator.available_headroom_mw:g}"
        )
    elif generator:
        failed.append(
            f"mw <= generator.available_headroom_mw: {intent.mw:g} > "
            f"{generator.available_headroom_mw:g}"
        )
        repair.append(f"Reduce mw to <= {generator.available_headroom_mw:g}.")

    if generator and target and generator.zone == target.zone:
        passed.append(f"generator.zone supports target_dc.zone: {generator.zone} == {target.zone}")
    elif generator and target:
        failed.append(f"generator.zone supports target_dc.zone: {generator.zone} != {target.zone}")
        repair.append("Choose a generator in the target data center zone.")

    _check_positive_mw(intent, passed, failed, repair)
    normalized = (
        _normalized_generation_intent(generator.id, target.id, intent.mw)
        if not failed and generator and target
        else None
    )
    return _planner_validation(intent, normalized, passed, failed, repair)


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


def _validate_curtail_load_for_planner(state: GridState, intent: ActionIntent) -> ActionIntentValidation:
    passed: list[str] = []
    failed: list[str] = []
    repair: list[str] = []
    dc = _data_center(state, intent.dc) if intent.dc else None

    if dc:
        passed.append(f"dc exists in data_centers: {dc.id}")
    else:
        failed.append(f"dc exists in data_centers: {intent.dc}")
        repair.append("Choose dc from available data_centers.")

    if dc and intent.mw <= dc.flexible_mw:
        passed.append(f"mw <= dc.flexible_mw: {intent.mw:g} <= {dc.flexible_mw:g}")
    elif dc:
        failed.append(f"mw <= dc.flexible_mw: {intent.mw:g} > {dc.flexible_mw:g}")
        repair.append(f"Reduce mw to <= {dc.flexible_mw:g}.")

    _check_positive_mw(intent, passed, failed, repair)
    normalized = _normalized_curtail_intent(dc.id, intent.mw) if not failed and dc else None
    return _planner_validation(intent, normalized, passed, failed, repair)


def _data_center(state: GridState, data_center_id: str):
    return next((dc for dc in state.data_centers if dc.id == data_center_id), None)


def _string_param(params: dict[str, str | float], key: str) -> str | None:
    value = params.get(key)
    return value if isinstance(value, str) else None


def _valid(action: Action) -> ActionValidation:
    return ActionValidation(valid=True, reason="Action is feasible for the current grid state.", action=action)


def _invalid(reason: str) -> ActionValidation:
    return ActionValidation(valid=False, reason=reason)


def _planner_validation(
    intent: ActionIntent,
    normalized: ActionIntent | None,
    passed: list[str],
    failed: list[str],
    repair: list[str],
) -> ActionIntentValidation:
    return ActionIntentValidation(
        valid=not failed,
        action_intent=intent,
        normalized_action_intent=normalized,
        passed_checks=passed,
        failed_checks=failed,
        repair_guidance=repair,
    )


def _check_positive_mw(
    intent: ActionIntent,
    passed: list[str],
    failed: list[str],
    repair: list[str],
) -> None:
    if intent.mw > 0:
        passed.append(f"mw > 0: {intent.mw:g} > 0")
    else:
        failed.append(f"mw > 0: {intent.mw:g} <= 0")
        repair.append("Use a positive mw value.")


def _normalized_shift_intent(from_dc: str, to_dc: str, mw: float) -> ActionIntent:
    return ActionIntent(
        type="shift_data_center_load",
        from_dc=from_dc,
        to_dc=to_dc,
        battery_id=None,
        generator_id=None,
        target_dc=None,
        dc=None,
        mw=mw,
    )


def _normalized_battery_intent(battery_id: str, target_dc: str, mw: float) -> ActionIntent:
    return ActionIntent(
        type="dispatch_battery",
        from_dc=None,
        to_dc=None,
        battery_id=battery_id,
        generator_id=None,
        target_dc=target_dc,
        dc=None,
        mw=mw,
    )


def _normalized_generation_intent(generator_id: str, target_dc: str, mw: float) -> ActionIntent:
    return ActionIntent(
        type="increase_local_generation",
        from_dc=None,
        to_dc=None,
        battery_id=None,
        generator_id=generator_id,
        target_dc=target_dc,
        dc=None,
        mw=mw,
    )


def _normalized_curtail_intent(dc: str, mw: float) -> ActionIntent:
    return ActionIntent(
        type="curtail_flexible_load",
        from_dc=None,
        to_dc=None,
        battery_id=None,
        generator_id=None,
        target_dc=None,
        dc=dc,
        mw=mw,
    )
