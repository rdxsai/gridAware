from __future__ import annotations

import json

from gridaware.agents.models import AgentRunTrace, AgentToolCallTrace, PlannerReport
from gridaware.planner_coverage import check_planner_coverage
from gridaware.scenarios import load_agent_grid, load_agent_scenario
from gridaware.tool_executor import GridToolRuntime


def test_planner_coverage_rejects_shallow_severe_plan() -> None:
    grid_state = load_agent_grid("case33bw_data_center_spike_tricky")
    available_controls = GridToolRuntime(
        scenario_bundle=load_agent_scenario("case33bw_data_center_spike_tricky")
    ).get_available_controls()
    report = PlannerReport.model_validate(
        {
            "scenario_id": "case33bw_data_center_spike_tricky",
            "planning_summary": "Only one shallow candidate.",
            "primary_objectives": ["Clear overload and low voltage."],
            "primitive_action_inventory": [],
            "candidates": [
                {
                    "rank": 1,
                    "archetype": "minimal_candidate",
                    "action_sequence": [_planner_intent("dispatch_battery")],
                    "validation_passed": True,
                    "validation_passed_checks": ["backend validation passed"],
                    "target_violations": ["line_25", "DC_A"],
                    "feasibility_checks": ["BAT_A has available MW."],
                    "expected_effect": "Reduce imports.",
                    "rationale": "Try battery first.",
                    "risk_notes": [],
                    "planner_confidence": "medium",
                }
            ],
            "rejected_options": [],
            "requires_simulation": True,
        }
    )

    result = check_planner_coverage(report, grid_state, available_controls)

    assert result.passed is False
    assert {issue.code for issue in result.issues} >= {
        "missing_required_archetypes",
        "missing_primitive_inventory",
    }


def test_planner_coverage_accepts_max_composite_for_tricky_case() -> None:
    grid_state = load_agent_grid("case33bw_data_center_spike_tricky")
    available_controls = GridToolRuntime(
        scenario_bundle=load_agent_scenario("case33bw_data_center_spike_tricky")
    ).get_available_controls()
    report = PlannerReport.model_validate(
        {
            "scenario_id": "case33bw_data_center_spike_tricky",
            "planning_summary": "Systematic severe-case candidates.",
            "primary_objectives": ["Clear overload and low voltage."],
            "primitive_action_inventory": [
                _primitive("shift_data_center_load"),
                _primitive("curtail_flexible_load"),
                _primitive("dispatch_battery"),
                _primitive("increase_local_generation"),
                _primitive("adjust_reactive_support"),
            ],
            "candidates": [
                _candidate(1, "minimal_candidate", [_planner_intent("adjust_reactive_support")]),
                _candidate(
                    2,
                    "thermal_first_candidate",
                    [
                        _planner_intent("shift_data_center_load"),
                        _planner_intent("curtail_flexible_load"),
                    ],
                ),
                _candidate(
                    3,
                    "voltage_first_candidate",
                    [
                        _planner_intent("adjust_reactive_support"),
                        _planner_intent("dispatch_battery"),
                    ],
                ),
                _candidate(
                    4,
                    "balanced_candidate",
                    [
                        _planner_intent("dispatch_battery"),
                        _planner_intent("increase_local_generation"),
                        _planner_intent("adjust_reactive_support"),
                    ],
                ),
                _candidate(
                    5,
                    "max_feasible_composite_candidate",
                    [
                        _planner_intent("shift_data_center_load"),
                        _planner_intent("curtail_flexible_load"),
                        _planner_intent("dispatch_battery"),
                        _planner_intent("increase_local_generation"),
                        _planner_intent("adjust_reactive_support"),
                    ],
                ),
            ],
            "rejected_options": [],
            "requires_simulation": True,
        }
    )

    result = check_planner_coverage(report, grid_state, available_controls)

    assert result.passed is True


def test_planner_coverage_rejects_unvalidated_final_actions() -> None:
    grid_state = load_agent_grid("case33bw_data_center_spike_tricky")
    available_controls = GridToolRuntime(
        scenario_bundle=load_agent_scenario("case33bw_data_center_spike_tricky")
    ).get_available_controls()
    report = PlannerReport.model_validate(
        {
            "scenario_id": "case33bw_data_center_spike_tricky",
            "planning_summary": "Systematic severe-case candidates.",
            "primary_objectives": ["Clear overload and low voltage."],
            "primitive_action_inventory": [
                _primitive("shift_data_center_load"),
                _primitive("curtail_flexible_load"),
                _primitive("dispatch_battery"),
                _primitive("increase_local_generation"),
                _primitive("adjust_reactive_support"),
            ],
            "candidates": [
                _candidate(1, "minimal_candidate", [_planner_intent("adjust_reactive_support")]),
                _candidate(2, "thermal_first_candidate", [_planner_intent("dispatch_battery")]),
                _candidate(
                    3,
                    "voltage_first_candidate",
                    [_planner_intent("adjust_reactive_support")],
                ),
                _candidate(4, "balanced_candidate", [_planner_intent("dispatch_battery")]),
                _candidate(
                    5,
                    "max_feasible_composite_candidate",
                    [
                        _planner_intent("shift_data_center_load"),
                        _planner_intent("curtail_flexible_load"),
                        _planner_intent("dispatch_battery"),
                        _planner_intent("increase_local_generation"),
                        _planner_intent("adjust_reactive_support"),
                    ],
                ),
            ],
            "rejected_options": [],
            "requires_simulation": True,
        }
    )
    trace = AgentRunTrace(
        tool_calls=[
            _validation_call(_backend_intent("dispatch_battery")),
            _validation_call(_backend_intent("adjust_reactive_support")),
        ]
    )

    result = check_planner_coverage(report, grid_state, available_controls, trace)

    assert result.passed is False
    assert "missing_action_validation" in {issue.code for issue in result.issues}


def _candidate(rank: int, archetype: str, actions: list[dict]) -> dict:
    return {
        "rank": rank,
        "archetype": archetype,
        "action_sequence": actions,
        "validation_passed": True,
        "validation_passed_checks": ["backend validation passed"],
        "target_violations": ["line_25", "DC_A"],
        "feasibility_checks": ["all checks passed"],
        "expected_effect": "Improve the active violations.",
        "rationale": "Required archetype.",
        "risk_notes": [],
        "planner_confidence": "high",
    }


def _primitive(action_type: str) -> dict:
    return {
        "action_type": action_type,
        "target": "DC_A",
        "max_value": 0.2,
        "units": "MW" if action_type != "adjust_reactive_support" else "MVAr",
        "primary_effect": "thermal_and_voltage",
        "backend_action_intent": _backend_intent(action_type),
        "rationale": f"{action_type} is available.",
    }


def _planner_intent(action_type: str) -> dict:
    return _backend_intent(action_type) | {
        "intent_summary": f"Use {action_type}.",
        "target_element": "DC_A",
        "control_asset": "DC_A",
        "setpoint": None,
        "units": "MW" if action_type != "adjust_reactive_support" else "MVAr",
    }


def _backend_intent(action_type: str) -> dict:
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
    match action_type:
        case "shift_data_center_load":
            intent.update({"from_dc": "DC_A", "to_dc": "DC_B", "mw": 0.15})
        case "curtail_flexible_load":
            intent.update({"dc": "DC_A", "mw": 0.15})
        case "dispatch_battery":
            intent.update({"battery_id": "BAT_A", "target_dc": "DC_A", "mw": 0.2})
        case "increase_local_generation":
            intent.update({"generator_id": "GEN_A", "target_dc": "DC_A", "mw": 0.2})
        case "adjust_reactive_support":
            intent.update({"resource_id": "VAR_A", "target_bus": "DC_A", "q_mvar": 0.2})
    return intent


def _validation_call(action_intent: dict) -> AgentToolCallTrace:
    return AgentToolCallTrace(
        name="validate_action_intent",
        arguments=json.dumps({"action_intent": action_intent}),
        output=json.dumps(
            {
                "ok": True,
                "validation": {
                    "valid": True,
                    "action_intent": action_intent,
                    "normalized_action_intent": action_intent,
                    "passed_checks": ["valid"],
                    "failed_checks": [],
                    "repair_guidance": [],
                },
            }
        ),
    )
