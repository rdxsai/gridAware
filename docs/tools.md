# Agent Tool Contract

The agent tool surface is intentionally small and stateful. Agents may reason about grid actions,
but the backend owns validation, simulation, evaluation, and mutation.

Tool definitions live in `src/gridaware/agent_tools.py`. Runtime execution lives in
`src/gridaware/tool_executor.py`.

## Tools

### `get_grid_state`

No parameters.

Returns the active scenario state: violations, bus voltages, line loading, data centers, batteries,
local generators, and health score.

### `propose_grid_actions`

Parameters:

```json
{
  "target_violation_id": "line_4"
}
```

Returns backend-generated candidate actions. These are safe examples and reusable action IDs, not the
only actions the agent can consider.

### `simulate_action`

Parameters use exactly one of `action_id` or `action_intent`.

Backend candidate:

```json
{
  "action_id": "A1",
  "action_intent": null
}
```

Agent-authored intent:

```json
{
  "action_id": null,
  "action_intent": {
    "type": "shift_data_center_load",
    "from_dc": "DC_A",
    "to_dc": "DC_B",
    "battery_id": null,
    "generator_id": null,
    "target_dc": null,
    "dc": null,
    "mw": 15
  }
}
```

The backend validates feasibility before simulation. Invalid intents return an error and are not
stored for execution.

### `get_available_controls`

No parameters.

Returns the allowed mitigation action types and controllable assets. The planner uses this to reason
about feasibility before proposing structured action intents.

### `evaluate_action_result`

Parameters:

```json
{
  "action_id": "agent_intent_1"
}
```

Evaluates a previous simulation against deterministic safety checks:

```python
remaining_violations == []
after_score > before_score
max_line_loading <= 100
min_bus_voltage >= 0.95
```

### `apply_action`

Parameters:

```json
{
  "action_id": "agent_intent_1"
}
```

Applies only a previously simulated and accepted action. Unsimulated, unevaluated, failed, or stale
actions are refused.

### `compare_grid_states`

No parameters.

Returns original vs active grid summary: health score, violation counts, and applied action id.

## Agent Boundary

The model can choose from backend candidates or author structured action intents. It cannot mutate
state directly. The backend enforces asset existence, available MW, destination capacity, simulation
success, and evaluation acceptance before applying any action.

## Scenario Source

Agent grid states come from `load_agent_grid(...)` in `src/gridaware/scenarios.py`. The current
implementation uses pandapower benchmark networks as base topologies, applies a named scenario
variant, runs power flow, and converts the result into `GridState`.

Initial variants:

- `mv_data_center_spike`: CIGRE MV benchmark with data center load and a constrained corridor.
- `mv_renewable_drop`: CIGRE MV benchmark with reduced DER output.
- `mv_line_constraint`: CIGRE MV benchmark with a tighter line constraint.
- `lv_edge_data_center`: CIGRE LV benchmark with edge data center stress.
