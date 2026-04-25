from __future__ import annotations

from copy import deepcopy
from typing import Any

import pandapower as pp
from pandapower.auxiliary import LoadflowNotConverged

from gridaware.actions import validate_action_intent
from gridaware.models import ActionIntent, Battery, GridState, LocalGenerator
from gridaware.scenarios import (
    DataCenterSpec,
    ReactiveSupportSpec,
    ScenarioBundle,
    _grid_state_from_pandapower,
)


def simulate_action_intent_on_pandapower(
    bundle: ScenarioBundle,
    intent: ActionIntent,
) -> dict[str, Any]:
    sequence = simulate_action_sequence_on_pandapower(bundle, [intent])
    step = sequence["step_results"][0] if sequence["step_results"] else None
    if step is None:
        return {
            "ok": True,
            "power_flow_converged": False,
            "error": sequence["error"] or "No simulation step was produced.",
            "action_intent": intent.model_dump(mode="json"),
            "before_state": bundle.grid_state.model_dump(mode="json"),
            "after_state": None,
            "diff": None,
        }

    return {
        "ok": True,
        "power_flow_converged": step["power_flow_converged"],
        "error": step["error"],
        "action_intent": intent.model_dump(mode="json"),
        "before_state": step["before_state"],
        "after_state": step["after_state"],
        "diff": step["diff"],
    }


def simulate_action_sequence_on_pandapower(
    bundle: ScenarioBundle,
    intents: list[ActionIntent],
) -> dict[str, Any]:
    if not intents:
        raise ValueError("simulate_action_sequence requires at least one action_intent")

    net = deepcopy(bundle.net)
    data_centers = deepcopy(bundle.data_centers)
    batteries = deepcopy(bundle.batteries)
    local_generators = deepcopy(bundle.local_generators)
    reactive_resources = deepcopy(bundle.reactive_resources)
    current_state = bundle.grid_state
    step_results: list[dict[str, Any]] = []

    for step_index, intent in enumerate(intents, start=1):
        validation = validate_action_intent(
            current_state,
            intent,
            action_id=f"sequence_step_{step_index}",
        )
        if not validation.valid:
            step_results.append(
                {
                    "step_index": step_index,
                    "action_intent": intent.model_dump(mode="json"),
                    "validation_passed": False,
                    "validation_errors": [validation.reason],
                    "power_flow_converged": False,
                    "error": validation.reason,
                    "before_state": current_state.model_dump(mode="json"),
                    "after_state": None,
                    "diff": None,
                }
            )
            return _sequence_response(
                bundle=bundle,
                intents=intents,
                step_results=step_results,
                current_state=current_state,
                sequence_completed=False,
                failed_step_index=step_index,
                error=validation.reason,
            )

        before_state = current_state
        try:
            _apply_intent_to_net(
                net,
                data_centers,
                batteries,
                local_generators,
                reactive_resources,
                intent,
            )
            pp.runpp(net, numba=False, max_iteration=30)
            after_state = _grid_state_from_pandapower(
                net,
                bundle.scenario_id,
                data_centers,
                batteries,
                local_generators,
                reactive_resources,
                bundle.metadata,
            )
        except (LoadflowNotConverged, ValueError) as exc:
            step_results.append(
                {
                    "step_index": step_index,
                    "action_intent": intent.model_dump(mode="json"),
                    "validation_passed": True,
                    "validation_errors": [],
                    "power_flow_converged": False,
                    "error": str(exc),
                    "before_state": before_state.model_dump(mode="json"),
                    "after_state": None,
                    "diff": None,
                }
            )
            return _sequence_response(
                bundle=bundle,
                intents=intents,
                step_results=step_results,
                current_state=before_state,
                sequence_completed=False,
                failed_step_index=step_index,
                error=str(exc),
            )

        step_results.append(
            {
                "step_index": step_index,
                "action_intent": intent.model_dump(mode="json"),
                "validation_passed": True,
                "validation_errors": [],
                "power_flow_converged": True,
                "error": None,
                "before_state": before_state.model_dump(mode="json"),
                "after_state": after_state.model_dump(mode="json"),
                "diff": _grid_diff(before_state, after_state),
            }
        )
        current_state = after_state

    return _sequence_response(
        bundle=bundle,
        intents=intents,
        step_results=step_results,
        current_state=current_state,
        sequence_completed=True,
        failed_step_index=None,
        error=None,
    )


def simulate_candidate_sequences_on_pandapower(
    bundle: ScenarioBundle,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    if not candidates:
        raise ValueError("simulate_candidate_sequences requires at least one candidate")

    candidate_results = []
    for index, candidate in enumerate(candidates, start=1):
        action_intents = candidate.get("action_intents")
        if not isinstance(action_intents, list):
            raise ValueError("Each candidate requires action_intents")

        intents = [ActionIntent.model_validate(action_intent) for action_intent in action_intents]
        result = simulate_action_sequence_on_pandapower(bundle, intents)
        candidate_results.append(
            {
                "candidate_id": str(candidate.get("candidate_id") or f"candidate_{index}"),
                "rank": int(candidate.get("rank") or index),
                "result": result,
            }
        )

    return {"ok": True, "candidate_results": candidate_results}


def _sequence_response(
    *,
    bundle: ScenarioBundle,
    intents: list[ActionIntent],
    step_results: list[dict[str, Any]],
    current_state: GridState,
    sequence_completed: bool,
    failed_step_index: int | None,
    error: str | None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "sequence_completed": sequence_completed,
        "failed_step_index": failed_step_index,
        "error": error,
        "action_intents": [intent.model_dump(mode="json") for intent in intents],
        "before_state": bundle.grid_state.model_dump(mode="json"),
        "final_state": current_state.model_dump(mode="json") if step_results else None,
        "final_diff": _grid_diff(bundle.grid_state, current_state) if step_results else None,
        "step_results": step_results,
    }


def _apply_intent_to_net(
    net: pp.pandapowerNet,
    data_centers: list[DataCenterSpec],
    batteries: list[Battery],
    local_generators: list[LocalGenerator],
    reactive_resources: list[ReactiveSupportSpec],
    intent: ActionIntent,
) -> None:
    match intent.type:
        case "shift_data_center_load":
            source = _data_center(data_centers, intent.from_dc)
            target = _data_center(data_centers, intent.to_dc)
            _adjust_dc_load(net, source, -intent.mw)
            _adjust_dc_load(net, target, intent.mw)
            source.display_load_mw -= intent.mw
            source.flexible_mw -= intent.mw
            target.display_load_mw += intent.mw
        case "curtail_flexible_load":
            dc = _data_center(data_centers, intent.dc)
            _adjust_dc_load(net, dc, -intent.mw)
            dc.display_load_mw -= intent.mw
            dc.flexible_mw -= intent.mw
        case "dispatch_battery":
            target = _data_center(data_centers, intent.target_dc)
            pp.create_sgen(
                net,
                bus=target.bus,
                p_mw=_display_mw_to_pp_mw(target, intent.mw),
                q_mvar=0.0,
                name=str(intent.battery_id),
            )
            battery = _battery(batteries, intent.battery_id)
            battery.available_mw -= intent.mw
        case "increase_local_generation":
            target = _data_center(data_centers, intent.target_dc)
            pp.create_sgen(
                net,
                bus=target.bus,
                p_mw=_display_mw_to_pp_mw(target, intent.mw),
                q_mvar=0.0,
                name=str(intent.generator_id),
            )
            generator = _local_generator(local_generators, intent.generator_id)
            generator.available_headroom_mw -= intent.mw
        case "adjust_reactive_support":
            target_bus = _target_bus_index(net, data_centers, intent.target_bus)
            pp.create_sgen(
                net,
                bus=target_bus,
                p_mw=0.0,
                q_mvar=float(intent.q_mvar),
                name=str(intent.resource_id),
            )
            resource = _reactive_resource(reactive_resources, intent.resource_id)
            resource.available_mvar -= float(intent.q_mvar)


def _adjust_dc_load(net: pp.pandapowerNet, dc: DataCenterSpec, display_delta_mw: float) -> None:
    if dc.load_index is None:
        raise ValueError(f"Data center {dc.data_center_id} has no pandapower load index")
    net.load.at[dc.load_index, "p_mw"] += _display_mw_to_pp_mw(dc, display_delta_mw)
    net.load.at[dc.load_index, "q_mvar"] += _display_mw_to_pp_q_mvar(dc, display_delta_mw)


def _display_mw_to_pp_mw(dc: DataCenterSpec, display_mw: float) -> float:
    return display_mw * dc.pp_mw_per_display_mw


def _display_mw_to_pp_q_mvar(dc: DataCenterSpec, display_mw: float) -> float:
    return display_mw * dc.pp_q_mvar_per_display_mw


def _data_center(data_centers: list[DataCenterSpec], data_center_id: str | None) -> DataCenterSpec:
    for data_center in data_centers:
        if data_center.data_center_id == data_center_id:
            return data_center
    raise ValueError(f"Unknown data center: {data_center_id}")


def _battery(batteries: list[Battery], battery_id: str | None) -> Battery:
    for battery in batteries:
        if battery.id == battery_id:
            return battery
    raise ValueError(f"Unknown battery: {battery_id}")


def _local_generator(
    local_generators: list[LocalGenerator], generator_id: str | None
) -> LocalGenerator:
    for generator in local_generators:
        if generator.id == generator_id:
            return generator
    raise ValueError(f"Unknown local generator: {generator_id}")


def _reactive_resource(
    reactive_resources: list[ReactiveSupportSpec], resource_id: str | None
) -> ReactiveSupportSpec:
    for resource in reactive_resources:
        if resource.resource_id == resource_id:
            return resource
    raise ValueError(f"Unknown reactive resource: {resource_id}")


def _target_bus_index(
    net: pp.pandapowerNet,
    data_centers: list[DataCenterSpec],
    target_bus: str | None,
) -> int:
    for data_center in data_centers:
        if data_center.data_center_id == target_bus:
            return data_center.bus
    if target_bus == "SUBSTATION":
        return int(net.ext_grid.iloc[0].bus)
    raise ValueError(f"Unknown target bus: {target_bus}")


def _grid_diff(before: GridState, after: GridState) -> dict[str, Any]:
    before_lines = {line.line: line.loading_percent for line in before.line_loadings}
    before_voltages = {voltage.bus: voltage.vm_pu for voltage in before.bus_voltages}
    before_violations = {(violation.type, violation.element_id) for violation in before.violations}
    after_violations = {(violation.type, violation.element_id) for violation in after.violations}

    return {
        "score_change": {
            "before": before.grid_health_score,
            "after": after.grid_health_score,
            "delta": after.grid_health_score - before.grid_health_score,
        },
        "resolved_violations": [
            {"type": violation_type, "element_id": element_id}
            for violation_type, element_id in sorted(before_violations - after_violations)
        ],
        "new_violations": [
            {"type": violation_type, "element_id": element_id}
            for violation_type, element_id in sorted(after_violations - before_violations)
        ],
        "remaining_violations": [
            violation.model_dump(mode="json") for violation in after.violations
        ],
        "line_loading_changes": [
            {
                "line": line.line,
                "before_percent": before_lines[line.line],
                "after_percent": line.loading_percent,
                "delta_percent": round(line.loading_percent - before_lines[line.line], 3),
            }
            for line in after.line_loadings
        ],
        "voltage_changes": [
            {
                "bus": voltage.bus,
                "before_vm_pu": before_voltages[voltage.bus],
                "after_vm_pu": voltage.vm_pu,
                "delta_vm_pu": round(voltage.vm_pu - before_voltages[voltage.bus], 4),
            }
            for voltage in after.bus_voltages
        ],
    }
