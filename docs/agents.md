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

Purpose: create ranked mitigation action intents for later simulation.

Allowed tools:

- `get_grid_state`
- `get_available_controls`

Forbidden tools:

- `propose_grid_actions`
- `simulate_action`
- `evaluate_action_result`
- `apply_action`
- `compare_grid_states`

Output:

- `PlannerReport` from `src/gridaware/agents/models.py`
- Each candidate includes a structured `action_intent`.
- Each candidate includes explicit `feasibility_checks` using numbers from grid/control state.
- `requires_simulation` must be `true`.

Runtime path:

```text
GridOrchestrator.run_planner(...)
  -> load_agent_grid(...)
  -> GridToolRuntime(...)
  -> run_analyzer_agent(...)
  -> run_planner_agent(...)
  -> planner calls get_grid_state and get_available_controls
  -> validate PlannerReport
```

## Deterministic Orchestrator

`GridOrchestrator` is currently deterministic code, not an LLM. It selects the scenario, creates the
tool runtime, gives each agent only its allowed tools, and validates the agent output.

Run manually:

```bash
uv run python scripts/run_analyzer.py --scenario mv_data_center_spike
uv run python scripts/run_planner.py --scenario mv_data_center_spike
```
