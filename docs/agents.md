# Agent Design

gridAware uses deterministic orchestration around constrained LLM agents. Python owns workflow
control and grid state. Agents reason inside narrow role boundaries.

## Analyzer Agent

Purpose: diagnose the active grid state.

Allowed tools:

- `get_grid_state`

Forbidden behavior:

- Do not propose mitigation actions.
- Do not simulate actions.
- Do not apply actions.
- Do not invent grid elements or measurements.

Output:

- `AnalyzerReport` from `src/gridaware/agents/models.py`
- `violating_*` fields contain only assets outside limits.
- `watchlist_*` fields contain near-limit assets that are not currently violating.

Runtime path:

```text
GridOrchestrator.run_analyzer(...)
  -> load_agent_grid(...)
  -> GridToolRuntime(...)
  -> run_analyzer_agent(...)
  -> Responses API call with only get_grid_state
  -> execute function_call_output loop
  -> validate AnalyzerReport
```

## Planner Agent

Purpose: create ranked mitigation action sequences for later simulation.

Allowed tools:

- `get_grid_state`
- `get_available_controls`
- `build_candidate_archetypes`
- `validate_action_intent`

Forbidden tools:

- `propose_grid_actions`
- `simulate_action`
- `evaluate_action_result`
- `apply_action`
- `compare_grid_states`

Output:

- `PlannerReport` from `src/gridaware/agents/models.py`
- `primitive_action_inventory` lists feasible primitive controls inspected before candidate ranking.
- Each candidate includes an explicit archetype: `minimal_candidate`, `thermal_first_candidate`,
  `voltage_first_candidate`, `balanced_candidate`, or `max_feasible_composite_candidate`.
- Each candidate includes a structured `action_sequence`; one-step sequences are valid.
- Each candidate includes explicit `feasibility_checks` using numbers from grid/control state.
- `requires_simulation` must be `true`.

Runtime path:

```text
GridOrchestrator.run_planner(...)
  -> load_agent_grid(...)
  -> GridToolRuntime(...)
  -> run_analyzer_agent(...)
  -> run_planner_agent(...)
  -> planner calls get_grid_state, get_available_controls, build_candidate_archetypes,
     and validate_action_intent
  -> deterministic planner coverage check
  -> one repair pass if required archetypes or max-composite coverage are missing
  -> validate PlannerReport schema
```

## Simulator Agent

Purpose: simulate validated planner action sequences and explain before/after grid changes.

Allowed tools:

- `simulate_action_sequence`

Forbidden behavior:

- Do not invent new actions.
- Do not apply actions to the active grid.
- Do not call planner, validation, evaluation, apply, or compare tools.

Output:

- `SimulatorReport` from `src/gridaware/agents/models.py`
- Each candidate result describes sequence completion, failed step if any, successful changes,
  failed changes, remaining violations, and final grid status.
- `final_grid_state` is the simulated `after_state` for the best candidate, not an applied active
  grid state.

Runtime path:

```text
GridOrchestrator.run_simulator(...)
  -> load_agent_scenario(...)
  -> GridToolRuntime(...)
  -> run_analyzer_agent(...)
  -> run_planner_agent(...)
  -> run_simulator_agent(...)
  -> simulator calls simulate_action_sequence for planner candidates
  -> validate SimulatorReport
```

## Deterministic Orchestrator

`GridOrchestrator` is currently deterministic code, not an LLM. It selects the scenario, creates the
tool runtime, gives each agent only its allowed tools, and validates the agent output.

Run manually:

```bash
uv run python scripts/run_analyzer.py --scenario mv_data_center_spike
uv run python scripts/run_planner.py --scenario mv_data_center_spike
uv run python scripts/run_simulator.py --scenario mv_data_center_spike
```
