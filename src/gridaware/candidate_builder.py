from __future__ import annotations

from typing import Any

from gridaware.models import ActionType, DataCenterLoad, GridState


def build_candidate_archetypes(
    state: GridState,
    allowed_action_types: list[ActionType],
) -> dict[str, Any]:
    """Build non-physics planner search scaffolding from controls and grid state."""

    allowed = set(allowed_action_types)
    stressed_dc = _stressed_data_center(state)
    primitive_actions = _primitive_action_inventory(state, allowed, stressed_dc)
    archetypes = _candidate_archetypes(state, allowed, stressed_dc)
    return {
        "ok": True,
        "severity_triggers": _severity_triggers(state),
        "primitive_action_inventory": primitive_actions,
        "candidate_archetypes": archetypes,
        "construction_notes": [
            "This tool does not run power flow or predict outcomes.",
            "Validate every action intent before including it in PlannerReport.",
            "Simulation remains required before any recommendation can be accepted.",
        ],
    }


def _severity_triggers(state: GridState) -> dict[str, Any]:
    worst_line_loading = max(
        (line.loading_percent for line in state.line_loadings),
        default=0.0,
    )
    min_voltage = min((bus.vm_pu for bus in state.bus_voltages), default=1.0)
    return {
        "active_violation_count": len(state.violations),
        "worst_line_loading_percent": round(worst_line_loading, 3),
        "minimum_bus_voltage_pu": round(min_voltage, 4),
        "requires_max_feasible_composite": (
            len(state.violations) >= 2 or worst_line_loading > 115 or min_voltage < 0.93
        ),
    }


def _primitive_action_inventory(
    state: GridState,
    allowed: set[ActionType],
    stressed_dc: DataCenterLoad | None,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if stressed_dc is None:
        return actions

    if "shift_data_center_load" in allowed:
        receiver = _best_shift_receiver(state, stressed_dc)
        if receiver is not None:
            mw = _round_mw(min(stressed_dc.flexible_mw, _receiving_headroom(receiver)))
            if mw > 0:
                actions.append(
                    _primitive(
                        "shift_data_center_load",
                        f"{stressed_dc.id}->{receiver.id}",
                        mw,
                        "MW",
                        "thermal_and_voltage",
                        _intent(
                            "shift_data_center_load",
                            from_dc=stressed_dc.id,
                            to_dc=receiver.id,
                            mw=mw,
                        ),
                        (
                            f"Move up to {mw:g} MW from {stressed_dc.id} to {receiver.id} "
                            "using source flexibility and receiver headroom."
                        ),
                    )
                )

    if "curtail_flexible_load" in allowed and stressed_dc.flexible_mw > 0:
        mw = _round_mw(stressed_dc.flexible_mw)
        actions.append(
            _primitive(
                "curtail_flexible_load",
                stressed_dc.id,
                mw,
                "MW",
                "thermal_and_voltage",
                _intent("curtail_flexible_load", dc=stressed_dc.id, mw=mw),
                f"Curtail up to {mw:g} MW of flexible load at {stressed_dc.id}.",
            )
        )

    if "dispatch_battery" in allowed:
        for battery in state.batteries:
            if battery.available_mw <= 0:
                continue
            target = _target_dc_for_zone(state, battery.zone, stressed_dc)
            if target is None:
                continue
            mw = _round_mw(battery.available_mw)
            actions.append(
                _primitive(
                    "dispatch_battery",
                    battery.id,
                    mw,
                    "MW",
                    "thermal_and_voltage",
                    _intent(
                        "dispatch_battery",
                        battery_id=battery.id,
                        target_dc=target.id,
                        mw=mw,
                    ),
                    f"Dispatch up to {mw:g} MW from {battery.id} toward {target.id}.",
                )
            )

    if "increase_local_generation" in allowed:
        for generator in state.local_generators:
            if generator.available_headroom_mw <= 0:
                continue
            target = _target_dc_for_zone(state, generator.zone, stressed_dc)
            if target is None:
                continue
            mw = _round_mw(generator.available_headroom_mw)
            actions.append(
                _primitive(
                    "increase_local_generation",
                    generator.id,
                    mw,
                    "MW",
                    "thermal_and_voltage",
                    _intent(
                        "increase_local_generation",
                        generator_id=generator.id,
                        target_dc=target.id,
                        mw=mw,
                    ),
                    f"Increase {generator.id} by up to {mw:g} MW toward {target.id}.",
                )
            )

    if "adjust_reactive_support" in allowed:
        target_bus = stressed_dc.id
        for resource in state.reactive_resources:
            if resource.available_mvar <= 0:
                continue
            target = _target_dc_for_zone(state, resource.zone, stressed_dc)
            if target is not None:
                target_bus = target.id
            q_mvar = _round_mw(resource.available_mvar)
            actions.append(
                _primitive(
                    "adjust_reactive_support",
                    resource.id,
                    q_mvar,
                    "MVAr",
                    "voltage",
                    _intent(
                        "adjust_reactive_support",
                        resource_id=resource.id,
                        target_bus=target_bus,
                        q_mvar=q_mvar,
                    ),
                    f"Inject up to {q_mvar:g} MVAr from {resource.id} toward {target_bus}.",
                )
            )

    return actions


def _candidate_archetypes(
    state: GridState,
    allowed: set[ActionType],
    stressed_dc: DataCenterLoad | None,
) -> list[dict[str, Any]]:
    if stressed_dc is None:
        return []

    split = _flex_split_for_data_center(state, stressed_dc)
    reactive = _first_reactive_intent(state, allowed, stressed_dc)
    battery = _first_battery_intent(state, allowed, stressed_dc)
    generator = _first_generation_intent(state, allowed, stressed_dc)
    shift = split["shift"]
    curtail = split["curtail"]

    return [
        _archetype(
            "minimal_candidate",
            "Smallest plausible low-disruption control sequence.",
            _compact([reactive, battery or generator or shift or curtail]),
        ),
        _archetype(
            "thermal_first_candidate",
            "Prioritize reducing overloaded corridor real-power flow.",
            _compact([shift, curtail, battery, generator]),
        ),
        _archetype(
            "voltage_first_candidate",
            "Prioritize low-voltage mitigation, then add real-power support.",
            _compact([reactive, battery, generator, curtail]),
        ),
        _archetype(
            "balanced_candidate",
            "Combine voltage support with real-power demand reduction and local support.",
            _compact([shift, battery, generator, reactive]),
        ),
        _archetype(
            "max_feasible_composite_candidate",
            "Use every non-conflicting relevant control at feasible values for severe violations.",
            _compact([shift, curtail, battery, generator, reactive]),
        ),
    ]


def _flex_split_for_data_center(
    state: GridState,
    stressed_dc: DataCenterLoad,
) -> dict[str, dict[str, Any] | None]:
    receiver = _best_shift_receiver(state, stressed_dc)
    shift_mw = 0.0
    shift = None
    if receiver is not None:
        shift_mw = _round_mw(min(stressed_dc.flexible_mw, _receiving_headroom(receiver)))
        if shift_mw > 0:
            shift = _intent(
                "shift_data_center_load",
                from_dc=stressed_dc.id,
                to_dc=receiver.id,
                mw=shift_mw,
            )

    remaining_flex = _round_mw(max(stressed_dc.flexible_mw - shift_mw, 0.0))
    curtail = None
    if remaining_flex > 0:
        curtail = _intent("curtail_flexible_load", dc=stressed_dc.id, mw=remaining_flex)
    return {"shift": shift, "curtail": curtail}


def _first_battery_intent(
    state: GridState,
    allowed: set[ActionType],
    stressed_dc: DataCenterLoad,
) -> dict[str, Any] | None:
    if "dispatch_battery" not in allowed:
        return None
    for battery in state.batteries:
        target = _target_dc_for_zone(state, battery.zone, stressed_dc)
        if battery.available_mw > 0 and target is not None:
            return _intent(
                "dispatch_battery",
                battery_id=battery.id,
                target_dc=target.id,
                mw=_round_mw(battery.available_mw),
            )
    return None


def _first_generation_intent(
    state: GridState,
    allowed: set[ActionType],
    stressed_dc: DataCenterLoad,
) -> dict[str, Any] | None:
    if "increase_local_generation" not in allowed:
        return None
    for generator in state.local_generators:
        target = _target_dc_for_zone(state, generator.zone, stressed_dc)
        if generator.available_headroom_mw > 0 and target is not None:
            return _intent(
                "increase_local_generation",
                generator_id=generator.id,
                target_dc=target.id,
                mw=_round_mw(generator.available_headroom_mw),
            )
    return None


def _first_reactive_intent(
    state: GridState,
    allowed: set[ActionType],
    stressed_dc: DataCenterLoad,
) -> dict[str, Any] | None:
    if "adjust_reactive_support" not in allowed:
        return None
    for resource in state.reactive_resources:
        target = _target_dc_for_zone(state, resource.zone, stressed_dc)
        if resource.available_mvar > 0 and target is not None:
            return _intent(
                "adjust_reactive_support",
                resource_id=resource.id,
                target_bus=target.id,
                q_mvar=_round_mw(resource.available_mvar),
            )
    return None


def _stressed_data_center(state: GridState) -> DataCenterLoad | None:
    violating_buses = {
        violation.element_id
        for violation in state.violations
        if violation.type in {"voltage_low", "voltage_high"}
    }
    for dc in state.data_centers:
        if dc.id in violating_buses:
            return dc
    voltage_by_bus = {voltage.bus: voltage.vm_pu for voltage in state.bus_voltages}
    data_centers_with_voltage = [dc for dc in state.data_centers if dc.id in voltage_by_bus]
    if data_centers_with_voltage:
        return min(data_centers_with_voltage, key=lambda dc: voltage_by_bus[dc.id])
    return state.data_centers[0] if state.data_centers else None


def _target_dc_for_zone(
    state: GridState,
    zone: str,
    fallback: DataCenterLoad | None,
) -> DataCenterLoad | None:
    for dc in state.data_centers:
        if dc.zone == zone:
            return dc
    return fallback


def _best_shift_receiver(state: GridState, source: DataCenterLoad) -> DataCenterLoad | None:
    receivers = [
        dc for dc in state.data_centers if dc.id != source.id and _receiving_headroom(dc) > 0
    ]
    return max(receivers, key=_receiving_headroom) if receivers else None


def _receiving_headroom(dc: DataCenterLoad) -> float:
    return max(dc.max_load_mw - dc.load_mw, 0.0)


def _primitive(
    action_type: ActionType,
    target: str,
    max_value: float,
    units: str,
    primary_effect: str,
    backend_action_intent: dict[str, Any],
    rationale: str,
) -> dict[str, Any]:
    return {
        "action_type": action_type,
        "target": target,
        "max_value": max_value,
        "units": units,
        "primary_effect": primary_effect,
        "backend_action_intent": backend_action_intent,
        "rationale": rationale,
    }


def _archetype(
    archetype: str,
    purpose: str,
    action_intents: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "archetype": archetype,
        "purpose": purpose,
        "candidate_shape": [intent["type"] for intent in action_intents],
        "action_intents": action_intents,
    }


def _intent(action_type: ActionType, **kwargs: Any) -> dict[str, Any]:
    intent = {
        "type": action_type,
        "from_dc": None,
        "to_dc": None,
        "battery_id": None,
        "generator_id": None,
        "target_dc": None,
        "dc": None,
        "resource_id": None,
        "target_bus": None,
        "q_mvar": None,
        "mw": None,
    }
    intent.update(kwargs)
    return intent


def _compact(values: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
    return [value for value in values if value is not None]


def _round_mw(value: float) -> float:
    return round(value, 3)
