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

### `build_candidate_archetypes`

No parameters.

Returns non-physics planner search scaffolding:

- `primitive_action_inventory`: feasible primitive backend-shaped intents available in the current scenario.
- `candidate_archetypes`: required candidate shapes such as `minimal_candidate`,
  `thermal_first_candidate`, `voltage_first_candidate`, `balanced_candidate`, and
  `max_feasible_composite_candidate`.
- `severity_triggers`: whether the current grid is severe enough to require a max-feasible composite.

This tool does not simulate outcomes. The planner must still call `validate_action_intent` for every
action it includes in final candidates.

### `validate_action_intent`

Parameters:

```json
{
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

Returns deterministic feasibility results: `valid`, `passed_checks`, `failed_checks`,
`repair_guidance`, and a normalized intent when valid. The planner should call this before including
an action intent in its final report.

### `simulate_action_sequence`

Parameters:

```json
{
  "action_intents": [
    {
      "type": "dispatch_battery",
      "from_dc": null,
      "to_dc": null,
      "battery_id": "BAT_A",
      "generator_id": null,
      "target_dc": "DC_A",
      "dc": null,
      "mw": 0.25
    },
    {
      "type": "curtail_flexible_load",
      "from_dc": null,
      "to_dc": null,
      "battery_id": null,
      "generator_id": null,
      "target_dc": null,
      "dc": "DC_A",
      "mw": 0.25
    }
  ]
}
```

Runs a pandapower-backed cumulative simulation on one copy of the baseline scenario network. A
single action is represented as a one-item sequence. Each step starts from the previous step's
simulated state, consumes remaining control availability, reruns power flow, and records a step diff.
The tool returns step results, the final state, and the final before/after diff. It does not apply
the sequence to the active grid.

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

The model can choose from backend candidates or author structured action sequences. It cannot mutate
state directly. The backend enforces asset existence, available MW, destination capacity, cumulative
control depletion, simulation success, and evaluation acceptance before applying any action.

## Scenario Source

Agent grid states come from `load_agent_grid(...)` in `src/gridaware/scenarios.py`. The current
implementation uses pandapower benchmark networks as base topologies, applies a named scenario
variant, runs power flow, and converts the result into `GridState`.

Initial variants:

- `baseline_case33bw`: untouched `pandapower.networks.case33bw()` benchmark for comparison.
- `case33bw_data_center_spike`: `case33bw` benchmark with documented downstream
  data-center load, local flexibility resources, and a constrained feeder corridor.
- `case33bw_data_center_spike_hard`: tougher `case33bw` data-center spike with smaller
  per-action flexibility limits, intended to expose partial single-action mitigations.
- `mv_data_center_spike`: CIGRE MV benchmark with data center load and a constrained corridor.
- `mv_renewable_drop`: CIGRE MV benchmark with reduced DER output.
- `mv_line_constraint`: CIGRE MV benchmark with a tighter line constraint.
- `lv_edge_data_center`: CIGRE LV benchmark with edge data center stress.

Scenario bundles carry metadata with the base network, scenario type, purpose, documented
modifications, and limitations. The `case33bw_data_center_spike` scenario is a benchmark-based
synthetic stress test: outputs are computed by pandapower, and the modifications are disclosed
rather than presented as an untouched utility grid.
