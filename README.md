# gridAware

Grid-aware AI agent MVP for data center load optimization.

The first version is intentionally small: deterministic grid tools, a safe action library,
an evaluator, a FastAPI surface, and a Streamlit demo shell. The agent layer can call these
tools through OpenAI Responses API and LangGraph without letting the model invent unsafe grid
operations.

## Quick Start

```bash
uv sync --extra dev
uv run gridaware-demo
```

Run the API:

```bash
uv run uvicorn gridaware.api:app --reload
```

Run the Streamlit UI:

```bash
uv run streamlit run src/gridaware/ui.py
```

Run tests:

```bash
uv run pytest
```

## MVP Flow

1. Load the demo grid scenario.
2. Inspect overloads and voltage violations.
3. Propose safe mitigation actions from a fixed action library.
4. Simulate each action without changing the active grid.
5. Evaluate actions against deterministic safety criteria.
6. Apply the best passing action.
7. Return a before/after report.

## Next Implementation Targets

- Replace heuristic simulation with a calibrated `pandapower` network model.
- Add a LangGraph state machine around the current deterministic tools.
- Add OpenAI Responses API tool-calling inside analyzer/planner/report nodes.
- Expand the UI with before/after charts and an agent trace timeline.
