from __future__ import annotations

from copy import deepcopy
from typing import Any

import pandapower as pp
from pandapower.auxiliary import LoadflowNotConverged

from gridaware.models import ActionIntent, GridState
from gridaware.scenarios import DataCenterSpec, ScenarioBundle, _grid_state_from_pandapower


def simulate_action_intent_on_pandapower(
    bundle: ScenarioBundle,
    intent: ActionIntent,
) -> dict[str, Any]:
    net = deepcopy(bundle.net)
    data_centers = deepcopy(bundle.data_centers)

    try:
        _apply_intent_to_net(net, data_centers, intent)
        pp.runpp(net, numba=False, max_iteration=30)
        after_state = _grid_state_from_pandapower(
            net,
            bundle.scenario_id,
            data_centers,
            bundle.batteries,
            bundle.local_generators,
            bundle.metadata,
        )
    except (LoadflowNotConverged, ValueError) as exc:
        return {
            "ok": True,
            "power_flow_converged": False,
            "error": str(exc),
            "action_intent": intent.model_dump(mode="json"),
            "before_state": bundle.grid_state.model_dump(mode="json"),
            "after_state": None,
            "diff": None,
        }

    return {
        "ok": True,
        "power_flow_converged": True,
        "error": None,
        "action_intent": intent.model_dump(mode="json"),
        "before_state": bundle.grid_state.model_dump(mode="json"),
        "after_state": after_state.model_dump(mode="json"),
        "diff": _grid_diff(bundle.grid_state, after_state),
    }


def _apply_intent_to_net(
    net: pp.pandapowerNet,
    data_centers: list[DataCenterSpec],
    intent: ActionIntent,
) -> None:
    match intent.type:
        case "shift_data_center_load":
            source = _data_center(data_centers, intent.from_dc)
            target = _data_center(data_centers, intent.to_dc)
            _adjust_dc_load(net, source, -intent.mw)
            _adjust_dc_load(net, target, intent.mw)
            source.display_load_mw -= intent.mw
            target.display_load_mw += intent.mw
        case "curtail_flexible_load":
            dc = _data_center(data_centers, intent.dc)
            _adjust_dc_load(net, dc, -intent.mw)
            dc.display_load_mw -= intent.mw
        case "dispatch_battery":
            target = _data_center(data_centers, intent.target_dc)
            pp.create_sgen(
                net,
                bus=target.bus,
                p_mw=_display_mw_to_pp_mw(target, intent.mw),
                q_mvar=0.0,
                name=str(intent.battery_id),
            )
        case "increase_local_generation":
            target = _data_center(data_centers, intent.target_dc)
            pp.create_sgen(
                net,
                bus=target.bus,
                p_mw=_display_mw_to_pp_mw(target, intent.mw),
                q_mvar=0.0,
                name=str(intent.generator_id),
            )


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
