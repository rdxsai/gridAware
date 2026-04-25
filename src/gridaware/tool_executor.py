from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from gridaware.actions import propose_grid_actions, validate_action_intent_for_planner
from gridaware.models import ActionIntent, Evaluation, GridState
from gridaware.pandapower_simulator import (
    simulate_action_intent_on_pandapower,
    simulate_action_sequence_on_pandapower,
    simulate_candidate_sequences_on_pandapower,
)
from gridaware.scenarios import ScenarioBundle, load_demo_scenario
from gridaware.simulator import (
    evaluate_result,
    get_grid_state,
    simulate_action,
    simulate_action_intent,
)


class GridToolRuntime:
    """Stateful executor for Responses API function calls."""

    def __init__(
        self,
        initial_state: GridState | None = None,
        scenario_bundle: ScenarioBundle | None = None,
    ) -> None:
        self.scenario_bundle = deepcopy(scenario_bundle)
        if initial_state is not None:
            self.original_state = deepcopy(initial_state)
        elif scenario_bundle is not None:
            self.original_state = deepcopy(scenario_bundle.grid_state)
        else:
            self.original_state = deepcopy(load_demo_scenario())
        self.active_state = deepcopy(self.original_state)
        self._simulations = {}
        self._evaluations: dict[str, Evaluation] = {}
        self._next_intent_id = 1
        self._applied_action_id: str | None = None

    def execute(self, name: str, arguments: dict[str, Any] | str | None) -> str:
        args = _normalize_arguments(arguments)
        try:
            match name:
                case "get_grid_state":
                    payload = self.get_grid_state()
                case "propose_grid_actions":
                    payload = self.propose_grid_actions(args["target_violation_id"])
                case "get_available_controls":
                    payload = self.get_available_controls()
                case "validate_action_intent":
                    payload = self.validate_action_intent(args["action_intent"])
                case "simulate_action":
                    payload = self.simulate_action(args["action_id"], args["action_intent"])
                case "simulate_action_intent":
                    payload = self.simulate_action_intent(args["action_intent"])
                case "simulate_action_sequence":
                    payload = self.simulate_action_sequence(args["action_intents"])
                case "simulate_candidate_sequences":
                    payload = self.simulate_candidate_sequences(args["candidates"])
                case "evaluate_action_result":
                    payload = self.evaluate_action_result(args["action_id"])
                case "apply_action":
                    payload = self.apply_action(args["action_id"])
                case "compare_grid_states":
                    payload = self.compare_grid_states()
                case _:
                    return _json_error(f"Unknown tool: {name}")
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            return _json_error(str(exc))

        return json.dumps(payload, separators=(",", ":"))

    def get_grid_state(self) -> dict[str, Any]:
        return {"ok": True, "grid_state": get_grid_state(self.active_state).model_dump(mode="json")}

    def propose_grid_actions(self, target_violation_id: str | None) -> dict[str, Any]:
        actions = propose_grid_actions(self.active_state, target_violation_id)
        return {"ok": True, "actions": [action.model_dump(mode="json") for action in actions]}

    def get_available_controls(self) -> dict[str, Any]:
        allowed_action_types = (
            self.scenario_bundle.allowed_action_types
            if self.scenario_bundle is not None
            else [
                "shift_data_center_load",
                "dispatch_battery",
                "increase_local_generation",
                "curtail_flexible_load",
            ]
        )
        return {
            "ok": True,
            "allowed_action_types": allowed_action_types,
            "data_centers": [
                {
                    "id": dc.id,
                    "zone": dc.zone,
                    "load_mw": dc.load_mw,
                    "flexible_mw": dc.flexible_mw,
                    "max_load_mw": dc.max_load_mw,
                    "receiving_headroom_mw": round(dc.max_load_mw - dc.load_mw, 3),
                }
                for dc in self.active_state.data_centers
            ],
            "batteries": [
                battery.model_dump(mode="json") for battery in self.active_state.batteries
            ],
            "local_generators": [
                generator.model_dump(mode="json")
                for generator in self.active_state.local_generators
            ],
            "reactive_resources": [
                resource.model_dump(mode="json")
                for resource in self.active_state.reactive_resources
            ],
            "control_assets": {
                "data_centers": [
                    {
                        "id": dc.id,
                        "zone": dc.zone,
                        "load_mw": dc.load_mw,
                        "flexible_mw": dc.flexible_mw,
                        "max_load_mw": dc.max_load_mw,
                        "receiving_headroom_mw": round(dc.max_load_mw - dc.load_mw, 3),
                    }
                    for dc in self.active_state.data_centers
                ],
                "batteries": [
                    battery.model_dump(mode="json") for battery in self.active_state.batteries
                ],
                "local_generators": [
                    generator.model_dump(mode="json")
                    for generator in self.active_state.local_generators
                ],
                "reactive_resources": [
                    resource.model_dump(mode="json")
                    for resource in self.active_state.reactive_resources
                ],
                "capacitor_banks": [],
                "transformers": [],
                "switches": [],
            },
            "action_feasibility_policy": _action_feasibility_policy(),
        }

    def simulate_action(
        self, action_id: str | None, action_intent: dict[str, Any] | None
    ) -> dict[str, Any]:
        if bool(action_id) == bool(action_intent):
            raise ValueError("Provide exactly one of action_id or action_intent")

        if action_id:
            result = simulate_action(self.active_state, action_id)
        else:
            intent_id = self._allocate_intent_id()
            result = simulate_action_intent(
                self.active_state, ActionIntent.model_validate(action_intent), intent_id
            )

        self._simulations[result.action_id] = result
        return {"ok": True, "simulation": result.model_dump(mode="json")}

    def simulate_action_intent(self, action_intent: dict[str, Any]) -> dict[str, Any]:
        if self.scenario_bundle is None:
            raise ValueError("simulate_action_intent requires a scenario bundle")
        return simulate_action_intent_on_pandapower(
            self.scenario_bundle,
            ActionIntent.model_validate(action_intent),
        )

    def simulate_action_sequence(self, action_intents: list[dict[str, Any]]) -> dict[str, Any]:
        if self.scenario_bundle is None:
            raise ValueError("simulate_action_sequence requires a scenario bundle")
        return simulate_action_sequence_on_pandapower(
            self.scenario_bundle,
            [ActionIntent.model_validate(action_intent) for action_intent in action_intents],
        )

    def simulate_candidate_sequences(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        if self.scenario_bundle is None:
            raise ValueError("simulate_candidate_sequences requires a scenario bundle")
        return simulate_candidate_sequences_on_pandapower(self.scenario_bundle, candidates)

    def validate_action_intent(self, action_intent: dict[str, Any]) -> dict[str, Any]:
        validation = validate_action_intent_for_planner(
            self.active_state,
            ActionIntent.model_validate(action_intent),
        )
        return {"ok": True, "validation": validation.model_dump(mode="json")}

    def evaluate_action_result(self, action_id: str) -> dict[str, Any]:
        result = self._simulations.get(action_id)
        if result is None:
            raise ValueError(f"Action has not been simulated: {action_id}")

        evaluation = evaluate_result(result)
        self._evaluations[action_id] = evaluation
        return {"ok": True, "evaluation": evaluation.model_dump(mode="json")}

    def apply_action(self, action_id: str) -> dict[str, Any]:
        result = self._simulations.get(action_id)
        evaluation = self._evaluations.get(action_id)
        if result is None:
            raise ValueError(f"Action has not been simulated: {action_id}")
        if evaluation is None:
            raise ValueError(f"Action has not been evaluated: {action_id}")
        if not evaluation.accepted or not result.success:
            raise ValueError(f"Refusing to apply unsafe action: {action_id}")

        self.active_state = deepcopy(result.predicted_state)
        self._applied_action_id = action_id
        return {
            "ok": True,
            "applied": True,
            "action_id": action_id,
            "new_grid_health_score": self.active_state.grid_health_score,
            "state": self.active_state.model_dump(mode="json"),
        }

    def compare_grid_states(self) -> dict[str, Any]:
        return {
            "ok": True,
            "summary": {
                "original_score": self.original_state.grid_health_score,
                "final_score": self.active_state.grid_health_score,
                "violations_before": len(self.original_state.violations),
                "violations_after": len(self.active_state.violations),
                "applied_action_id": self._applied_action_id,
            },
        }

    def _allocate_intent_id(self) -> str:
        action_id = f"agent_intent_{self._next_intent_id}"
        self._next_intent_id += 1
        return action_id


def _normalize_arguments(arguments: dict[str, Any] | str | None) -> dict[str, Any]:
    if arguments is None:
        return {}
    if isinstance(arguments, str):
        return json.loads(arguments)
    return arguments


def _json_error(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, separators=(",", ":"))


def _action_feasibility_policy() -> dict[str, Any]:
    return {
        "shift_data_center_load": {
            "required_fields": ["from_dc", "to_dc", "mw"],
            "valid_checks": [
                "from_dc exists in data_centers",
                "to_dc exists in data_centers",
                "from_dc != to_dc",
                "mw <= from_dc.flexible_mw",
                "mw <= to_dc.receiving_headroom_mw",
            ],
        },
        "dispatch_battery": {
            "required_fields": ["battery_id", "target_dc", "mw"],
            "valid_checks": [
                "battery_id exists in batteries",
                "target_dc exists in data_centers",
                "mw <= battery.available_mw",
                "battery.zone should match target_dc.zone or support the target zone",
            ],
            "forbidden_checks": [
                "target_dc.receiving_headroom_mw",
                "target_dc.flexible_mw",
            ],
        },
        "increase_local_generation": {
            "required_fields": ["generator_id", "target_dc", "mw"],
            "valid_checks": [
                "generator_id exists in local_generators",
                "target_dc exists in data_centers",
                "mw <= generator.available_headroom_mw",
                "generator.zone should match target_dc.zone or support the target zone",
            ],
            "forbidden_checks": [
                "target_dc.receiving_headroom_mw",
                "target_dc.flexible_mw",
            ],
        },
        "curtail_flexible_load": {
            "required_fields": ["dc", "mw"],
            "valid_checks": [
                "dc exists in data_centers",
                "mw <= dc.flexible_mw",
            ],
            "forbidden_checks": [
                "receiving_headroom_mw",
                "battery.available_mw",
                "generator.available_headroom_mw",
            ],
        },
        "adjust_reactive_support": {
            "required_fields": ["resource_id", "target_bus", "q_mvar"],
            "valid_checks": [
                "resource_id exists in reactive_resources",
                "target_bus exists in bus_voltages",
                "q_mvar <= resource.available_mvar",
                "resource.zone should match target_bus zone or support the target zone",
            ],
            "forbidden_checks": [
                "mw",
                "target_dc.receiving_headroom_mw",
                "battery.available_mw",
                "generator.available_headroom_mw",
            ],
        },
    }
