from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from gridaware.actions import propose_grid_actions
from gridaware.models import ActionIntent, Evaluation, GridState
from gridaware.scenarios import load_demo_scenario
from gridaware.simulator import evaluate_result, get_grid_state, simulate_action, simulate_action_intent


class GridToolRuntime:
    """Stateful executor for Responses API function calls."""

    def __init__(self, initial_state: GridState | None = None) -> None:
        self.original_state = deepcopy(initial_state or load_demo_scenario())
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
                case "simulate_action":
                    payload = self.simulate_action(args["action_id"], args["action_intent"])
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
