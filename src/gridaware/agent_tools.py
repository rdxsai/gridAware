from __future__ import annotations

from typing import Any


ACTION_TYPE_ENUM = [
    "shift_data_center_load",
    "dispatch_battery",
    "increase_local_generation",
    "curtail_flexible_load",
    "adjust_reactive_support",
]


def responses_tool_definitions() -> list[dict[str, Any]]:
    """Return strict Responses API function tool definitions for grid agents."""

    return [
        {
            "type": "function",
            "name": "get_grid_state",
            "description": (
                "Inspect the active grid scenario, including violations, bus voltages, "
                "line loading, assets, data center loads, and grid health score."
            ),
            "parameters": _empty_parameters(),
            "strict": True,
        },
        {
            "type": "function",
            "name": "propose_grid_actions",
            "description": (
                "Return feasible mitigation candidates from the backend action library. "
                "Use this for safe examples before creating or simulating your own action intent."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_violation_id": {
                        "type": ["string", "null"],
                        "description": (
                            "Element id or violation id to target, such as line_4 or DC_A. "
                            "Use null to ask for actions for the current scenario."
                        ),
                    }
                },
                "required": ["target_violation_id"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "get_available_controls",
            "description": (
                "Return the allowed mitigation action types and controllable grid assets, including "
                "data center flexibility, receiving headroom, batteries, local generation, and "
                "reactive support."
            ),
            "parameters": _empty_parameters(),
            "strict": True,
        },
        {
            "type": "function",
            "name": "validate_action_intent",
            "description": (
                "Run deterministic backend feasibility checks for a drafted mitigation action "
                "intent. Use this before including any action_intent in the final planner report."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action_intent": {
                        **_action_intent_schema(),
                        "description": "Structured mitigation action intent to validate.",
                    }
                },
                "required": ["action_intent"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "simulate_action",
            "description": (
                "Validate and simulate a mitigation action without mutating the active grid. "
                "Provide either action_id from propose_grid_actions or a structured action_intent."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action_id": {
                        "type": ["string", "null"],
                        "description": (
                            "Candidate action id returned by propose_grid_actions. Use null when "
                            "providing action_intent."
                        ),
                    },
                    "action_intent": {
                        "anyOf": [_action_intent_schema(), {"type": "null"}],
                        "description": (
                            "Agent-authored structured mitigation action. Use null when using action_id."
                        ),
                    },
                },
                "required": ["action_id", "action_intent"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "simulate_action_sequence",
            "description": (
                "Run a pandapower-backed cumulative simulation for an ordered sequence of "
                "validated action_intents. A single-action candidate should be represented as "
                "a sequence with one action_intent. Each step starts from the previous step's "
                "simulated state and consumes remaining control availability."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action_intents": {
                        "type": "array",
                        "items": _action_intent_schema(),
                        "minItems": 1,
                        "description": (
                            "Ordered mitigation actions to simulate cumulatively from the "
                            "baseline scenario state."
                        ),
                    }
                },
                "required": ["action_intents"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "simulate_candidate_sequences",
            "description": (
                "Simulate every planner candidate in one call. Each candidate contains an "
                "ordered sequence of action_intents. Within a candidate, actions are applied "
                "cumulatively. Across candidates, each candidate starts from the same original "
                "stressed grid state so results are comparable."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "candidates": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "candidate_id": {
                                    "type": "string",
                                    "description": "Stable candidate identifier.",
                                },
                                "rank": {
                                    "type": "integer",
                                    "description": "Planner candidate rank.",
                                },
                                "action_intents": {
                                    "type": "array",
                                    "items": _action_intent_schema(),
                                    "minItems": 1,
                                    "description": "Ordered candidate action sequence.",
                                },
                            },
                            "required": ["candidate_id", "rank", "action_intents"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["candidates"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "evaluate_action_result",
            "description": (
                "Evaluate a previously simulated action against deterministic grid safety criteria."
            ),
            "parameters": _action_id_parameters(
                "Action id from a prior simulate_action call, including backend candidates or "
                "agent intent ids."
            ),
            "strict": True,
        },
        {
            "type": "function",
            "name": "apply_action",
            "description": (
                "Apply a previously simulated and accepted action to the active grid scenario. "
                "This refuses unsimulated, failed, or stale actions."
            ),
            "parameters": _action_id_parameters("Action id from an accepted simulation result."),
            "strict": True,
        },
        {
            "type": "function",
            "name": "compare_grid_states",
            "description": (
                "Compare the original grid state with the active grid state after any applied action."
            ),
            "parameters": _empty_parameters(),
            "strict": True,
        },
    ]


def _empty_parameters() -> dict[str, Any]:
    return {"type": "object", "properties": {}, "required": [], "additionalProperties": False}


def _action_id_parameters(description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action_id": {
                "type": "string",
                "description": description,
            }
        },
        "required": ["action_id"],
        "additionalProperties": False,
    }


def _action_intent_schema() -> dict[str, Any]:
    nullable_string = {
        "type": ["string", "null"],
        "description": "Required for some action types; use null when not applicable.",
    }
    return {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ACTION_TYPE_ENUM,
                "description": "Allowed mitigation action type.",
            },
            "from_dc": nullable_string,
            "to_dc": nullable_string,
            "battery_id": nullable_string,
            "generator_id": nullable_string,
            "target_dc": nullable_string,
            "dc": nullable_string,
            "resource_id": nullable_string,
            "target_bus": nullable_string,
            "q_mvar": {
                "type": ["number", "null"],
                "description": "Reactive power in MVAr for voltage-support actions.",
            },
            "mw": {
                "type": ["number", "null"],
                "description": "Megawatts to shift, dispatch, generate, or curtail.",
            },
        },
        "required": [
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
        ],
        "additionalProperties": False,
    }
