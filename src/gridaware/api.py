from __future__ import annotations

from fastapi import FastAPI, HTTPException

from gridaware.actions import propose_grid_actions
from gridaware.models import Action, AppliedAction, GridState, SimulationResult, WorkflowReport
from gridaware.scenarios import load_demo_scenario
from gridaware.simulator import apply_action, simulate_action
from gridaware.workflow import run_mitigation_workflow

app = FastAPI(title="gridAware API", version="0.1.0")

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
