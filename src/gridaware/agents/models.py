from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from gridaware.models import ViolationType


Severity = Literal["low", "medium", "high", "critical"]
RiskLevel = Literal["low", "medium", "high", "critical"]


class AnalyzerViolationFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ViolationType
    element_id: str
    observed: float
    limit: float
    units: str
    severity: Severity
    explanation: str


class AnalyzerReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    summary: str
    active_violations: list[AnalyzerViolationFinding]
    stressed_lines: list[str]
    stressed_buses: list[str]
    stressed_data_centers: list[str]
    risk_level: RiskLevel
    planner_focus: list[str]
    forbidden_next_steps: list[str]


class AgentToolCallTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: str
    output: str


class AgentRunTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_ids: list[str] = Field(default_factory=list)
    tool_calls: list[AgentToolCallTrace] = Field(default_factory=list)


class AnalyzerRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: AnalyzerReport
    trace: AgentRunTrace
