from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ViolationType = Literal["line_overload", "transformer_overload", "voltage_low", "voltage_high"]
ActionType = Literal[
    "shift_data_center_load",
    "dispatch_battery",
    "increase_local_generation",
    "curtail_flexible_load",
]


class Violation(BaseModel):
    type: ViolationType
    element_id: str
    observed: float
    limit: float
    units: str


class BusVoltage(BaseModel):
    bus: str
    vm_pu: float


class LineLoading(BaseModel):
    line: str
    loading_percent: float


class DataCenterLoad(BaseModel):
    id: str
    zone: str
    load_mw: float
    flexible_mw: float


class Battery(BaseModel):
    id: str
    zone: str
    available_mw: float


class LocalGenerator(BaseModel):
    id: str
    zone: str
    available_headroom_mw: float


class GridState(BaseModel):
    scenario_id: str
    bus_voltages: list[BusVoltage]
    line_loadings: list[LineLoading]
    data_centers: list[DataCenterLoad]
    batteries: list[Battery] = Field(default_factory=list)
    local_generators: list[LocalGenerator] = Field(default_factory=list)
    violations: list[Violation]
    grid_health_score: int


class Action(BaseModel):
    action_id: str
    type: ActionType
    description: str
    parameters: dict[str, str | float]
    estimated_cost: float


class LineLoadingChange(BaseModel):
    line: str
    before_percent: float
    after_percent: float


class VoltageChange(BaseModel):
    bus: str
    before_vm_pu: float
    after_vm_pu: float


class SimulationResult(BaseModel):
    action_id: str
    success: bool
    remaining_violations: list[Violation]
    before_score: int
    after_score: int
    max_line_loading: float
    min_bus_voltage: float
    line_loading_changes: list[LineLoadingChange]
    voltage_changes: list[VoltageChange]
    tradeoffs: list[str]
    predicted_state: GridState


class Evaluation(BaseModel):
    accepted: bool
    reason: str
    result: SimulationResult


class AppliedAction(BaseModel):
    applied: bool
    action_id: str
    new_grid_health_score: int
    state: GridState


class WorkflowReport(BaseModel):
    scenario_id: str
    original_score: int
    final_score: int
    violations_before: int
    violations_after: int
    selected_action: Action | None
    evaluated_actions: list[Evaluation]
    final_state: GridState
