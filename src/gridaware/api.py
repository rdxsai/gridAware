from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gridaware.actions import propose_grid_actions
from gridaware.agents.models import AnalyzerReport, PlannerReport
from gridaware.agents.planner import run_planner_agent
from gridaware.agents.responses_runner import create_openai_client
from gridaware.models import (
    Action,
    ActionIntent,
    AppliedAction,
    GridState,
    SimulationResult,
    WorkflowReport,
)
from gridaware.orchestrator import GridOrchestrator
from gridaware.pandapower_simulator import execute_intents_capturing_bundle
from gridaware.scenarios import (
    AgentGridScenario,
    ScenarioBundle,
    load_agent_scenario,
    load_demo_scenario,
)
from gridaware.simulator import apply_action, simulate_action
from gridaware.tool_executor import GridToolRuntime
from gridaware.topology import (
    CurrentTopologyView,
    build_current_topology_view,
    build_topology_view_from_bundle,
)
from gridaware.workflow import run_mitigation_workflow

app = FastAPI(title="gridAware API", version="0.1.0")
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_active_state = load_demo_scenario()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def root_app() -> str:
    return _topology_app_html()


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
    return _topology_app_html()


def _topology_app_html() -> str:
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


AnalyzerJobStatus = Literal["running", "complete", "failed"]


class AnalyzerJobState(BaseModel):
    job_id: str
    status: AnalyzerJobStatus
    started_at: float
    duration_s: float | None = None
    report: AnalyzerReport | None = None
    error: str | None = None
    grid_health_score: int | None = None
    max_line_loading_percent: float | None = None
    min_bus_voltage_pu: float | None = None


_analyzer_jobs: dict[str, AnalyzerJobState] = {}
_analyzer_jobs_lock = threading.Lock()


def _run_analyzer_job(job_id: str, scenario_id: AgentGridScenario) -> None:
    started = _analyzer_jobs[job_id].started_at
    try:
        result = GridOrchestrator().run_analyzer(scenario_id)
        snapshot_bundle = load_agent_scenario(scenario_id)
        snapshot = _snapshot(snapshot_bundle.grid_state)
        with _analyzer_jobs_lock:
            _analyzer_jobs[job_id] = AnalyzerJobState(
                job_id=job_id,
                status="complete",
                started_at=started,
                duration_s=round(time.time() - started, 2),
                report=result.report,
                grid_health_score=snapshot.grid_health_score,
                max_line_loading_percent=snapshot.max_line_loading_percent,
                min_bus_voltage_pu=snapshot.min_bus_voltage_pu,
            )
    except Exception as exc:  # noqa: BLE001 - surface to UI
        with _analyzer_jobs_lock:
            _analyzer_jobs[job_id] = AnalyzerJobState(
                job_id=job_id,
                status="failed",
                started_at=started,
                duration_s=round(time.time() - started, 2),
                error=str(exc),
            )


class AnalyzerJobCreated(BaseModel):
    job_id: str


@app.post("/grid/analyze", response_model=AnalyzerJobCreated)
def start_analyzer(
    scenario_id: AgentGridScenario = "case33bw_data_center_spike_tricky",
) -> AnalyzerJobCreated:
    job_id = uuid.uuid4().hex
    with _analyzer_jobs_lock:
        _analyzer_jobs[job_id] = AnalyzerJobState(
            job_id=job_id, status="running", started_at=time.time()
        )
    thread = threading.Thread(
        target=_run_analyzer_job, args=(job_id, scenario_id), daemon=True
    )
    thread.start()
    return AnalyzerJobCreated(job_id=job_id)


@app.get("/grid/analyze/{job_id}", response_model=AnalyzerJobState)
def get_analyzer_job(job_id: str) -> AnalyzerJobState:
    with _analyzer_jobs_lock:
        state = _analyzer_jobs.get(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Analyzer job {job_id!r} not found")
    return state


PlannerJobStatus = Literal["running", "complete", "failed"]


class PlannerJobState(BaseModel):
    job_id: str
    status: PlannerJobStatus
    started_at: float
    duration_s: float | None = None
    report: PlannerReport | None = None
    error: str | None = None


_planner_jobs: dict[str, PlannerJobState] = {}
_planner_jobs_lock = threading.Lock()


_PLANNER_MAX_ATTEMPTS = 3


def _run_planner_job(
    plan_job_id: str,
    scenario_id: AgentGridScenario,
    analyzer_report: AnalyzerReport,
) -> None:
    started = _planner_jobs[plan_job_id].started_at
    last_exc: Exception | None = None
    for attempt in range(1, _PLANNER_MAX_ATTEMPTS + 1):
        try:
            bundle = load_agent_scenario(scenario_id)
            runtime = GridToolRuntime(scenario_bundle=bundle)
            result = run_planner_agent(runtime, analyzer_report, client=create_openai_client())
            with _planner_jobs_lock:
                _planner_jobs[plan_job_id] = PlannerJobState(
                    job_id=plan_job_id,
                    status="complete",
                    started_at=started,
                    duration_s=round(time.time() - started, 2),
                    report=result.report,
                )
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            print(
                f"[planner] attempt {attempt}/{_PLANNER_MAX_ATTEMPTS} failed: {exc}",
                flush=True,
            )

    with _planner_jobs_lock:
        _planner_jobs[plan_job_id] = PlannerJobState(
            job_id=plan_job_id,
            status="failed",
            started_at=started,
            duration_s=round(time.time() - started, 2),
            error=str(last_exc) if last_exc else "Planner failed",
        )


class PlannerJobRequest(BaseModel):
    analyzer_job_id: str
    scenario_id: AgentGridScenario = "case33bw_data_center_spike_tricky"


class PlannerJobCreated(BaseModel):
    plan_job_id: str


@app.post("/grid/plan", response_model=PlannerJobCreated)
def start_planner(request: PlannerJobRequest) -> PlannerJobCreated:
    with _analyzer_jobs_lock:
        analyzer_state = _analyzer_jobs.get(request.analyzer_job_id)
    if analyzer_state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Analyzer job {request.analyzer_job_id!r} not found",
        )
    if analyzer_state.status != "complete" or analyzer_state.report is None:
        raise HTTPException(
            status_code=409,
            detail=f"Analyzer job {request.analyzer_job_id!r} is not complete",
        )

    plan_job_id = uuid.uuid4().hex
    with _planner_jobs_lock:
        _planner_jobs[plan_job_id] = PlannerJobState(
            job_id=plan_job_id, status="running", started_at=time.time()
        )
    thread = threading.Thread(
        target=_run_planner_job,
        args=(plan_job_id, request.scenario_id, analyzer_state.report),
        daemon=True,
    )
    thread.start()
    return PlannerJobCreated(plan_job_id=plan_job_id)


@app.get("/grid/plan/{plan_job_id}", response_model=PlannerJobState)
def get_planner_job(plan_job_id: str) -> PlannerJobState:
    with _planner_jobs_lock:
        state = _planner_jobs.get(plan_job_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Planner job {plan_job_id!r} not found")
    return state


ExecuteJobStatus = Literal["running", "complete", "failed"]
_EXECUTE_ORDER = (
    "shift_data_center_load",
    "curtail_flexible_load",
    "dispatch_battery",
    "increase_local_generation",
    "adjust_reactive_support",
)


class ExecuteMetricSnapshot(BaseModel):
    grid_health_score: int
    max_line_loading_percent: float
    min_bus_voltage_pu: float
    active_violations: int


class ExecuteActionResult(BaseModel):
    type: str
    intent_summary: str
    target: str
    setpoint: str | None = None
    applied: bool
    error: str | None = None
    loading_delta_percent: float | None = None
    voltage_delta_pu: float | None = None
    health_delta: int | None = None


class ExecuteReport(BaseModel):
    summary: str
    actions_executed: list[ExecuteActionResult]
    all_succeeded: bool
    metrics_before: ExecuteMetricSnapshot
    metrics_after: ExecuteMetricSnapshot
    remaining_violations: list[str]


class ExecuteJobState(BaseModel):
    job_id: str
    status: ExecuteJobStatus
    started_at: float
    duration_s: float | None = None
    report: ExecuteReport | None = None
    error: str | None = None


_execute_jobs: dict[str, ExecuteJobState] = {}
_execute_post_bundles: dict[str, ScenarioBundle] = {}
_execute_jobs_lock = threading.Lock()


def _dedupe_planner_intents(report: PlannerReport) -> list[tuple[ActionIntent, str]]:
    seen: dict[tuple, tuple[ActionIntent, str]] = {}
    for candidate in report.candidates:
        for intent in candidate.action_sequence:
            key = (
                intent.type,
                intent.battery_id,
                intent.generator_id,
                intent.resource_id,
                intent.target_dc,
                intent.dc,
                intent.from_dc,
                intent.to_dc,
                intent.target_bus,
                intent.mw,
                intent.q_mvar,
            )
            if key in seen:
                continue
            seen[key] = (
                ActionIntent(
                    type=intent.type,
                    from_dc=intent.from_dc,
                    to_dc=intent.to_dc,
                    battery_id=intent.battery_id,
                    generator_id=intent.generator_id,
                    target_dc=intent.target_dc,
                    dc=intent.dc,
                    resource_id=intent.resource_id,
                    target_bus=intent.target_bus,
                    q_mvar=intent.q_mvar,
                    mw=intent.mw,
                ),
                intent.intent_summary,
            )
    ordered = sorted(
        seen.values(),
        key=lambda pair: _EXECUTE_ORDER.index(pair[0].type)
        if pair[0].type in _EXECUTE_ORDER
        else len(_EXECUTE_ORDER),
    )
    return ordered


def _intent_target_label(intent: ActionIntent) -> str:
    if intent.type == "shift_data_center_load":
        return f"{intent.from_dc or '?'} → {intent.to_dc or '?'}"
    if intent.type == "dispatch_battery":
        return intent.battery_id or "battery"
    if intent.type == "increase_local_generation":
        return intent.generator_id or "generator"
    if intent.type == "curtail_flexible_load":
        return intent.target_dc or intent.dc or "data center"
    if intent.type == "adjust_reactive_support":
        return intent.resource_id or intent.target_bus or "VAR"
    return "—"


def _intent_setpoint_label(intent: ActionIntent) -> str | None:
    if intent.type == "adjust_reactive_support" and intent.q_mvar is not None:
        return f"{intent.q_mvar:.2f} MVAr"
    if intent.mw is not None:
        return f"{intent.mw:.2f} MW"
    return None


def _snapshot(state: GridState) -> ExecuteMetricSnapshot:
    max_loading = max((line.loading_percent for line in state.line_loadings), default=0.0)
    min_voltage = min((bus.vm_pu for bus in state.bus_voltages), default=1.0)
    return ExecuteMetricSnapshot(
        grid_health_score=state.grid_health_score,
        max_line_loading_percent=round(float(max_loading), 1),
        min_bus_voltage_pu=round(float(min_voltage), 3),
        active_violations=len(state.violations),
    )


def _run_execute_job(
    execute_job_id: str,
    scenario_id: AgentGridScenario,
    planner_report: PlannerReport,
) -> None:
    started = _execute_jobs[execute_job_id].started_at
    try:
        intent_pairs = _dedupe_planner_intents(planner_report)
        if not intent_pairs:
            raise ValueError("Planner produced no executable actions")

        bundle = load_agent_scenario(scenario_id)
        before = _snapshot(bundle.grid_state)
        intents = [pair[0] for pair in intent_pairs]
        post_bundle, step_results = execute_intents_capturing_bundle(bundle, intents)
        after = _snapshot(post_bundle.grid_state)

        applied_by_index = {step["step_index"] - 1: step for step in step_results}
        actions_executed = []
        for idx, (intent, summary) in enumerate(intent_pairs):
            step = applied_by_index.get(idx)
            loading_delta = None
            voltage_delta = None
            health_delta = None
            if step and step.get("applied"):
                loading_delta = round(
                    step["after"]["max_line_loading_percent"]
                    - step["before"]["max_line_loading_percent"],
                    1,
                )
                voltage_delta = round(
                    step["after"]["min_bus_voltage_pu"]
                    - step["before"]["min_bus_voltage_pu"],
                    3,
                )
                health_delta = (
                    step["after"]["grid_health_score"] - step["before"]["grid_health_score"]
                )
            actions_executed.append(
                ExecuteActionResult(
                    type=intent.type,
                    intent_summary=summary,
                    target=_intent_target_label(intent),
                    setpoint=_intent_setpoint_label(intent),
                    applied=bool(step and step.get("applied")),
                    error=step.get("error") if step else "Not reached",
                    loading_delta_percent=loading_delta,
                    voltage_delta_pu=voltage_delta,
                    health_delta=health_delta,
                )
            )

        all_succeeded = all(item.applied for item in actions_executed)
        delta_health = after.grid_health_score - before.grid_health_score
        delta_loading = before.max_line_loading_percent - after.max_line_loading_percent
        delta_voltage = after.min_bus_voltage_pu - before.min_bus_voltage_pu
        if all_succeeded:
            summary_text = (
                f"Applied {len(actions_executed)} actions. "
                f"Grid health rose by {delta_health} points, max line loading dropped "
                f"by {delta_loading:.1f}%, and minimum bus voltage rose by "
                f"{delta_voltage:+.3f} pu."
            )
        else:
            failed = next(item for item in actions_executed if not item.applied)
            summary_text = (
                f"Stopped at {failed.type}: {failed.error or 'unknown error'}. "
                f"Partial mitigation applied; {after.active_violations} violation(s) remain."
            )

        remaining = [violation.type for violation in post_bundle.grid_state.violations]
        report = ExecuteReport(
            summary=summary_text,
            actions_executed=actions_executed,
            all_succeeded=all_succeeded,
            metrics_before=before,
            metrics_after=after,
            remaining_violations=remaining,
        )

        with _execute_jobs_lock:
            _execute_jobs[execute_job_id] = ExecuteJobState(
                job_id=execute_job_id,
                status="complete",
                started_at=started,
                duration_s=round(time.time() - started, 2),
                report=report,
            )
            _execute_post_bundles[execute_job_id] = post_bundle
    except Exception as exc:  # noqa: BLE001
        with _execute_jobs_lock:
            _execute_jobs[execute_job_id] = ExecuteJobState(
                job_id=execute_job_id,
                status="failed",
                started_at=started,
                duration_s=round(time.time() - started, 2),
                error=str(exc),
            )


class ExecuteJobRequest(BaseModel):
    plan_job_id: str
    scenario_id: AgentGridScenario = "case33bw_data_center_spike_tricky"


class ExecuteJobCreated(BaseModel):
    execute_job_id: str


@app.post("/grid/execute", response_model=ExecuteJobCreated)
def start_execute(request: ExecuteJobRequest) -> ExecuteJobCreated:
    with _planner_jobs_lock:
        plan_state = _planner_jobs.get(request.plan_job_id)
    if plan_state is None:
        raise HTTPException(
            status_code=404, detail=f"Planner job {request.plan_job_id!r} not found"
        )
    if plan_state.status != "complete" or plan_state.report is None:
        raise HTTPException(
            status_code=409, detail=f"Planner job {request.plan_job_id!r} is not complete"
        )

    job_id = uuid.uuid4().hex
    with _execute_jobs_lock:
        _execute_jobs[job_id] = ExecuteJobState(
            job_id=job_id, status="running", started_at=time.time()
        )
    thread = threading.Thread(
        target=_run_execute_job,
        args=(job_id, request.scenario_id, plan_state.report),
        daemon=True,
    )
    thread.start()
    return ExecuteJobCreated(execute_job_id=job_id)


@app.get("/grid/execute/{execute_job_id}", response_model=ExecuteJobState)
def get_execute_job(execute_job_id: str) -> ExecuteJobState:
    with _execute_jobs_lock:
        state = _execute_jobs.get(execute_job_id)
    if state is None:
        raise HTTPException(
            status_code=404, detail=f"Execute job {execute_job_id!r} not found"
        )
    return state


@app.get("/grid/topology/post-action/{execute_job_id}", response_model=CurrentTopologyView)
def get_post_action_topology(execute_job_id: str) -> CurrentTopologyView:
    with _execute_jobs_lock:
        bundle = _execute_post_bundles.get(execute_job_id)
        state = _execute_jobs.get(execute_job_id)
    if bundle is None or state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Post-action topology for {execute_job_id!r} not available",
        )
    return build_topology_view_from_bundle(bundle, bundle.scenario_id)
