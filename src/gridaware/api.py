from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from gridaware.actions import propose_grid_actions
from gridaware.models import Action, AppliedAction, GridState, SimulationResult, WorkflowReport
from gridaware.scenarios import AgentGridScenario, load_demo_scenario
from gridaware.simulator import apply_action, simulate_action
from gridaware.topology import CurrentTopologyView, build_current_topology_view
from gridaware.workflow import run_mitigation_workflow

app = FastAPI(title="gridAware API", version="0.1.0")
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_active_state = load_demo_scenario()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/scenario/reset", response_model=GridState)
def reset_scenario() -> GridState:
    global _active_state
    _active_state = load_demo_scenario()
    return _active_state


@app.get("/grid/state", response_model=GridState)
def get_state() -> GridState:
    return _active_state


@app.get("/grid/topology/current", response_model=CurrentTopologyView)
def get_current_topology(
    scenario_id: AgentGridScenario = "case33bw_data_center_spike_tricky",
) -> CurrentTopologyView:
    return build_current_topology_view(scenario_id)


@app.get("/app", response_class=HTMLResponse)
def topology_app() -> str:
    return (STATIC_DIR / "index.html").read_text()


@app.get("/grid/actions", response_model=list[Action])
def get_actions(target_violation: str | None = None) -> list[Action]:
    return propose_grid_actions(_active_state, target_violation)


@app.post("/grid/actions/{action_id}/simulate", response_model=SimulationResult)
def simulate(action_id: str) -> SimulationResult:
    try:
        return simulate_action(_active_state, action_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/grid/actions/{action_id}/apply", response_model=AppliedAction)
def apply(action_id: str) -> AppliedAction:
    global _active_state
    try:
        applied = apply_action(_active_state, action_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _active_state = applied.state
    return applied


@app.post("/workflow/run", response_model=WorkflowReport)
def run_workflow() -> WorkflowReport:
    global _active_state
    report = run_mitigation_workflow(_active_state)
    _active_state = report.final_state
    return report
