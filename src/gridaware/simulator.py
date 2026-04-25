from __future__ import annotations

from copy import deepcopy

from gridaware.actions import get_action_by_id, validate_action, validate_action_intent
from gridaware.models import (
    Action,
    ActionIntent,
    ActionValidation,
    AppliedAction,
    BusVoltage,
    Evaluation,
    GridState,
    LineLoading,
    LineLoadingChange,
    SimulationResult,
    Violation,
    VoltageChange,
)


def get_grid_state(state: GridState) -> GridState:
    return deepcopy(state)


def simulate_action(state: GridState, action_id: str) -> SimulationResult:
    action = get_action_by_id(state, action_id)
    validation = validate_action(state, action)
    if not validation.valid or validation.action is None:
        raise ValueError(validation.reason)

    return _simulate_validated_action(state, validation.action, validation)


def simulate_action_intent(
    state: GridState, intent: ActionIntent, action_id: str = "agent_intent"
) -> SimulationResult:
    validation = validate_action_intent(state, intent, action_id)
    if not validation.valid or validation.action is None:
        raise ValueError(validation.reason)

    return _simulate_validated_action(state, validation.action, validation)


def _simulate_validated_action(
    state: GridState, action: Action, validation: ActionValidation
) -> SimulationResult:
    predicted = _apply_action_to_copy(state, action)
    predicted.violations = _detect_violations(predicted)
    predicted.grid_health_score = _score_grid(predicted)

    max_line_loading = max(line.loading_percent for line in predicted.line_loadings)
    min_bus_voltage = min(voltage.vm_pu for voltage in predicted.bus_voltages)
    success = (
        not predicted.violations
        and predicted.grid_health_score > state.grid_health_score
        and max_line_loading <= 100.0
        and min_bus_voltage >= 0.95
    )

    return SimulationResult(
        action_id=action.action_id,
        validation=validation,
        success=success,
        remaining_violations=predicted.violations,
        before_score=state.grid_health_score,
        after_score=predicted.grid_health_score,
        max_line_loading=max_line_loading,
        min_bus_voltage=min_bus_voltage,
        line_loading_changes=_line_changes(state, predicted),
        voltage_changes=_voltage_changes(state, predicted),
        tradeoffs=_tradeoffs(action),
        predicted_state=predicted,
    )


def evaluate_result(result: SimulationResult) -> Evaluation:
    if result.success:
        return Evaluation(
            accepted=True,
            reason="Action removes violations, improves health score, and stays within limits.",
            result=result,
        )

    return Evaluation(
        accepted=False,
        reason="Action failed one or more safety checks.",
        result=result,
    )


def apply_action(state: GridState, action_id: str) -> AppliedAction:
    result = simulate_action(state, action_id)
    if not result.success:
        raise ValueError(f"Refusing to apply unsafe action {action_id}")

    return AppliedAction(
        applied=True,
        action_id=action_id,
        new_grid_health_score=result.after_score,
        state=result.predicted_state,
    )


def _apply_action_to_copy(state: GridState, action: Action) -> GridState:
    predicted = deepcopy(state)
    mw = float(action.parameters["mw"])

    match action.type:
        case "shift_data_center_load":
            _shift_load(predicted, str(action.parameters["from_dc"]), str(action.parameters["to_dc"]), mw)
            _adjust_line(predicted, "line_4", round(-1.62 * mw, 1))
            _adjust_voltage(predicted, "DC_A", round(0.0027 * mw, 3))
            _adjust_line(predicted, "line_7", round(0.53 * mw, 1))
        case "dispatch_battery":
            _adjust_line(predicted, "line_4", round(-1.5 * mw, 1))
            _adjust_voltage(predicted, "DC_A", round(0.0025 * mw, 3))
        case "increase_local_generation":
            _adjust_line(predicted, "line_4", round(-1.5 * mw, 1))
            _adjust_voltage(predicted, "DC_A", round(0.0025 * mw, 3))
        case "curtail_flexible_load":
            _shift_load(predicted, str(action.parameters["dc"]), str(action.parameters["dc"]), mw)
            _adjust_line(predicted, "line_4", round(-1.12 * mw, 1))
            _adjust_voltage(predicted, "DC_A", round(0.0019 * mw, 3))

    return predicted


def _shift_load(state: GridState, from_dc: str, to_dc: str, mw: float) -> None:
    for dc in state.data_centers:
        if dc.id == from_dc:
            dc.load_mw -= mw
        if dc.id == to_dc and to_dc != from_dc:
            dc.load_mw += mw


def _adjust_line(state: GridState, line_id: str, delta_percent: float) -> None:
    for line in state.line_loadings:
        if line.line == line_id:
            line.loading_percent = round(max(0.0, line.loading_percent + delta_percent), 1)


def _adjust_voltage(state: GridState, bus: str, delta_pu: float) -> None:
    for voltage in state.bus_voltages:
        if voltage.bus == bus:
            voltage.vm_pu = round(voltage.vm_pu + delta_pu, 3)


def _detect_violations(state: GridState) -> list[Violation]:
    violations: list[Violation] = []
    for line in state.line_loadings:
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

    for voltage in state.bus_voltages:
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


def _score_grid(state: GridState) -> int:
    max_line = max(line.loading_percent for line in state.line_loadings)
    min_voltage = min(voltage.vm_pu for voltage in state.bus_voltages)
    line_penalty = max(0.0, max_line - 85.0) * 1.1
    voltage_penalty = max(0.0, 0.98 - min_voltage) * 450.0
    violation_penalty = len(state.violations) * 8.0
    return round(max(0.0, min(100.0, 100.0 - line_penalty - voltage_penalty - violation_penalty)))


def _line_changes(before: GridState, after: GridState) -> list[LineLoadingChange]:
    after_by_line: dict[str, LineLoading] = {line.line: line for line in after.line_loadings}
    return [
        LineLoadingChange(
            line=line.line,
            before_percent=line.loading_percent,
            after_percent=after_by_line[line.line].loading_percent,
        )
        for line in before.line_loadings
    ]


def _voltage_changes(before: GridState, after: GridState) -> list[VoltageChange]:
    after_by_bus: dict[str, BusVoltage] = {voltage.bus: voltage for voltage in after.bus_voltages}
    return [
        VoltageChange(
            bus=voltage.bus,
            before_vm_pu=voltage.vm_pu,
            after_vm_pu=after_by_bus[voltage.bus].vm_pu,
        )
        for voltage in before.bus_voltages
    ]


def _tradeoffs(action: Action) -> list[str]:
    match action.type:
        case "shift_data_center_load":
            return ["DC_B absorbs 15 MW of extra flexible compute load but remains below limits."]
        case "dispatch_battery":
            return ["Battery state of charge is reduced and may need later recharge."]
        case "increase_local_generation":
            return ["Local generation dispatch cost increases for the interval."]
        case "curtail_flexible_load":
            return ["Non-critical data center work is deferred."]
