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

## Deterministic Orchestrator

`GridOrchestrator` is currently deterministic code, not an LLM. It selects the scenario, creates the
tool runtime, gives each agent only its allowed tools, and validates the agent output.

Run manually:

```bash
uv run python scripts/run_analyzer.py --scenario mv_data_center_spike
```
