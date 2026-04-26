from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from gridaware.agents.models import AgentRunTrace, CandidateArchetype, PlannerReport
from gridaware.models import GridState


REQUIRED_SEVERE_ARCHETYPES: set[CandidateArchetype] = {
    "minimal_candidate",
    "thermal_first_candidate",
    "voltage_first_candidate",
    "balanced_candidate",
    "max_feasible_composite_candidate",
}


class PlannerCoverageIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class PlannerCoverageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    severe_scenario: bool
    issues: list[PlannerCoverageIssue]


def check_planner_coverage(
    report: PlannerReport,
    grid_state: GridState,
    available_controls: dict[str, Any],
    trace: AgentRunTrace | None = None,
) -> PlannerCoverageResult:
    issues: list[PlannerCoverageIssue] = []
    severe = _severe_scenario(grid_state)

    if not report.candidates:
        issues.append(_issue("missing_candidates", "PlannerReport contains no candidates."))

    invalid_ranks = [
        candidate.rank for candidate in report.candidates if not candidate.validation_passed
    ]
    if invalid_ranks:
        issues.append(
            _issue(
                "invalid_candidate",
                f"All final candidates must be backend-validated; invalid ranks: {invalid_ranks}.",
            )
        )

    archetypes = {candidate.archetype for candidate in report.candidates}
    if severe:
        missing = sorted(REQUIRED_SEVERE_ARCHETYPES - archetypes)
        if missing:
            issues.append(
                _issue(
                    "missing_required_archetypes",
                    f"Severe scenario requires candidate archetypes: {missing}.",
                )
            )
        _check_max_composite_coverage(report, available_controls, issues)
    elif "minimal_candidate" not in archetypes:
        issues.append(
            _issue(
                "missing_minimal_candidate",
                "Non-severe scenarios still require at least one minimal_candidate.",
            )
        )

    inventory_types = {item.action_type for item in report.primitive_action_inventory}
    relevant_types = _relevant_available_action_types(available_controls)
    missing_inventory = sorted(relevant_types - inventory_types)
    if missing_inventory:
        issues.append(
            _issue(
                "missing_primitive_inventory",
                f"Primitive action inventory is missing available relevant controls: {missing_inventory}.",
            )
        )

    if trace is not None:
        _check_action_validation_coverage(report, trace, issues)

    return PlannerCoverageResult(
        passed=not issues,
        severe_scenario=severe,
        issues=issues,
    )


def _check_action_validation_coverage(
    report: PlannerReport,
    trace: AgentRunTrace,
    issues: list[PlannerCoverageIssue],
) -> None:
    required = {
        _planner_intent_signature(intent)
        for candidate in report.candidates
        for intent in candidate.action_sequence
    }
    validated = _validated_intent_signatures(trace)
    missing = sorted(required - validated)
    if missing:
        issues.append(
            _issue(
                "missing_action_validation",
                (
                    "Every unique final action_intent must have a matching valid "
                    f"validate_action_intent tool result; missing signatures: {missing}."
                ),
            )
        )


def _validated_intent_signatures(trace: AgentRunTrace) -> set[str]:
    signatures: set[str] = set()
    for call in trace.tool_calls:
        if call.name != "validate_action_intent":
            continue
        try:
            payload = json.loads(call.output)
        except json.JSONDecodeError:
            continue
        validation = payload.get("validation", {})
        if not validation.get("valid"):
            continue
        for key in ("normalized_action_intent", "action_intent"):
            action_intent = validation.get(key)
            if isinstance(action_intent, dict):
                signatures.add(_backend_intent_signature(action_intent))
    return signatures


def _check_max_composite_coverage(
    report: PlannerReport,
    available_controls: dict[str, Any],
    issues: list[PlannerCoverageIssue],
) -> None:
    max_candidates = [
        candidate
        for candidate in report.candidates
        if candidate.archetype == "max_feasible_composite_candidate"
    ]
    if not max_candidates:
        return

    relevant_types = _relevant_available_action_types(available_controls)
    best_coverage = max(
        (
            {intent.type for intent in candidate.action_sequence if intent.type in relevant_types}
            for candidate in max_candidates
        ),
        key=len,
        default=set(),
    )
    missing = sorted(relevant_types - best_coverage)
    if missing:
        issues.append(
            _issue(
                "incomplete_max_composite_candidate",
                (
                    "max_feasible_composite_candidate must include every relevant "
                    f"non-conflicting control type; missing: {missing}."
                ),
            )
        )


def _relevant_available_action_types(available_controls: dict[str, Any]) -> set[str]:
    allowed = set(available_controls.get("allowed_action_types", []))
    data_centers = available_controls.get("data_centers", [])
    batteries = available_controls.get("batteries", [])
    generators = available_controls.get("local_generators", [])
    reactive_resources = available_controls.get("reactive_resources", [])

    relevant: set[str] = set()
    if (
        "shift_data_center_load" in allowed
        and any(dc.get("flexible_mw", 0) > 0 for dc in data_centers)
        and any(dc.get("receiving_headroom_mw", 0) > 0 for dc in data_centers)
        and len(data_centers) >= 2
    ):
        relevant.add("shift_data_center_load")
    if "curtail_flexible_load" in allowed and any(
        dc.get("flexible_mw", 0) > 0 for dc in data_centers
    ):
        relevant.add("curtail_flexible_load")
    if "dispatch_battery" in allowed and any(
        battery.get("available_mw", 0) > 0 for battery in batteries
    ):
        relevant.add("dispatch_battery")
    if "increase_local_generation" in allowed and any(
        generator.get("available_headroom_mw", 0) > 0 for generator in generators
    ):
        relevant.add("increase_local_generation")
    if "adjust_reactive_support" in allowed and any(
        resource.get("available_mvar", 0) > 0 for resource in reactive_resources
    ):
        relevant.add("adjust_reactive_support")
    return relevant


def _severe_scenario(grid_state: GridState) -> bool:
    worst_line_loading = max(
        (line.loading_percent for line in grid_state.line_loadings),
        default=0.0,
    )
    minimum_voltage = min((bus.vm_pu for bus in grid_state.bus_voltages), default=1.0)
    return len(grid_state.violations) >= 2 or worst_line_loading > 115 or minimum_voltage < 0.93


def _issue(code: str, message: str) -> PlannerCoverageIssue:
    return PlannerCoverageIssue(code=code, message=message)


def _planner_intent_signature(intent: Any) -> str:
    return _backend_intent_signature(
        {
            "type": intent.type,
            "from_dc": intent.from_dc,
            "to_dc": intent.to_dc,
            "battery_id": intent.battery_id,
            "generator_id": intent.generator_id,
            "target_dc": intent.target_dc,
            "dc": intent.dc,
            "resource_id": intent.resource_id,
            "target_bus": intent.target_bus,
            "q_mvar": intent.q_mvar,
            "mw": intent.mw,
        }
    )


def _backend_intent_signature(intent: dict[str, Any]) -> str:
    keys = [
        "type",
        "from_dc",
        "to_dc",
        "battery_id",
        "generator_id",
        "target_dc",
        "dc",
        "resource_id",
        "target_bus",
        "q_mvar",
        "mw",
    ]
    normalized = {key: _normalize_number(intent.get(key)) for key in keys}
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _normalize_number(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    return value
