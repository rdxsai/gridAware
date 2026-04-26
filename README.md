# gridAware

An AI-agent demo that diagnoses and mitigates electrical-grid issues caused by data-center
demand spikes. Three agents — **analyzer**, **planner**, and **executor** — operate over a
synthetic distribution feeder built on the IEEE 33-bus benchmark, with a real
`pandapower` power-flow solver under the hood.

## What you'll see

A single-page topology UI showing a 12.66 kV distribution feeder serving an edge data
center (`DataCenter A`, ~1 MW), a partner facility on the same feeder, and a co-located
mix of battery storage, local generation, and reactive support. The default scenario
`case33bw_data_center_spike_tricky` puts `DataCenter A` into voltage sag (0.904 pu) and
overloads an upstream feeder segment (`Feeder 25` at 147% of its ampacity) — two
simultaneous violations that no single mitigation can clear.

The flow:

1. **Analyze grid** — runs the analyzer agent (OpenAI Responses API, ~10 s). Calls
   `get_grid_state` and emits a structured report listing each violation with severity and
   a plain-English explanation. Findings appear in a side panel; the topology recolors
   itself in red/amber to mark the agent's verdicts and shows the grid health score.
2. **Find actions** — runs the planner agent (~1–2 min). Enumerates five mitigation levers
   (load shifting, curtailment, battery dispatch, local generation, reactive support).
   Skipped tool-call validations are deterministically backfilled, and the orchestrator
   retries up to three times on coverage failures so demo runs stay reliable.
3. **Execute actions** — runs deterministically (~0.3 s, no LLM). Applies all five
   actions to a deep-copied pandapower net, re-runs the power flow, and returns
   before/after metrics. The topology recolors green for resolved violations, the impact
   card shows `health 0 → 91`, `loading 147% → 82%`, `voltage 0.904 → 0.961`,
   `violations 2 → 0`, and each action carries its own per-step delta.
4. **Reset grid** — restores the original neutral topology view for a repeat run.

The original grid is never mutated; execution always operates on a copy.

## Quick start

Requires Python 3.12+ and [uv](https://github.com/astral-sh/uv).

```bash
# 1. Install dependencies
uv sync --extra dev

# 2. Provide an OpenAI API key in .env
echo "OPENAI_API_KEY=sk-..." > .env
# (the runner also accepts OPEN_AI_API as an alias)

# 3. Start the FastAPI server
uv run uvicorn gridaware.api:app --port 8000
```

Open `http://localhost:8000/app` and click through:
**Analyze grid** → **Find actions** → **Execute actions** → **Reset grid**.

## Tests

```bash
uv run pytest
```

48 tests cover the agents, scenario builders, the deterministic simulator, the planner
coverage rules, and the topology view contract.

## Architecture

```
FastAPI server (src/gridaware/api.py)
   │
   ├── /grid/topology/current             ← neutral values-only view
   ├── /grid/topology/post-action/{id}    ← updated values after execution
   │
   ├── /grid/analyze   POST → background, GET → poll
   │     └── analyzer agent — OpenAI Responses API, structured report
   ├── /grid/plan      POST → background, GET → poll
   │     └── planner agent — Responses API, ≤32 tool rounds,
   │       validation backfill, up to 3 retries on coverage failure
   └── /grid/execute   POST → background, GET → poll
         └── deterministic action loop — pandapower power flow on a copy
```

The frontend (`src/gridaware/static/`) is vanilla HTML/CSS/JS with ES modules — no React,
no build step. The topology canvas uses a layered DOM (edges, nodes, labels) scaled into
a flex slot beside an instrument-style side panel. Three view modes — `neutral`,
`analyzed`, `executed` — drive the topology coloring as the agents complete.

## Files of interest

| File | What's in it |
|---|---|
| `src/gridaware/scenarios.py` | Synthetic scenario builders, including `case33bw_data_center_spike_tricky` |
| `src/gridaware/agents/analyzer.py` | Analyzer agent (Responses API + tool runtime) |
| `src/gridaware/agents/planner.py` | Planner agent + validation-backfill reliability layer |
| `src/gridaware/agents/prompts.py` | System prompts for each agent |
| `src/gridaware/pandapower_simulator.py` | Deterministic power-flow simulation; `execute_intents_capturing_bundle` runs the executor step |
| `src/gridaware/planner_coverage.py` | Deterministic acceptance rules for planner output |
| `src/gridaware/topology.py` | API view of the topology, supports both fresh and post-action bundles |
| `src/gridaware/api.py` | All HTTP endpoints + per-agent job registries |
| `src/gridaware/static/topology.js` | UI state machine (analyzer → planner → executor + cross-link flashing) |

## Demo framing notes

- The scenario is synthetic, built on the IEEE 33-bus benchmark feeder. Values are
  representative of a small-scale edge-data-center deployment, not a real utility feeder.
- The analyzer and planner are LLM-driven; the executor is deterministic.
- `Partner Facility` shares the same distribution feeder as `DataCenter A` — a realistic
  framing for paired/companion facilities used for workload balancing, not for failover.
- `Feeder 25` is rendered upstream of both data centers in the topology; its 147%
  loading reflects the cumulative downstream demand, not a line directly between the two
  DCs.
