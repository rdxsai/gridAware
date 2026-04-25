from __future__ import annotations

from gridaware.agents.analyzer import run_analyzer_agent
from gridaware.agents.models import AnalyzerRunResult, PlannerRunResult
from gridaware.agents.planner import run_planner_agent
from gridaware.agents.responses_runner import DEFAULT_AGENT_MODEL, ResponsesClient
from gridaware.scenarios import AgentGridScenario, load_agent_grid
from gridaware.tool_executor import GridToolRuntime


class GridOrchestrator:
    """Deterministic workflow controller for gridAware agent runs."""

    def __init__(self, *, client: ResponsesClient | None = None, model: str = DEFAULT_AGENT_MODEL) -> None:
        self.client = client
        self.model = model

    def run_analyzer(
        self, scenario_id: AgentGridScenario = "mv_data_center_spike"
    ) -> AnalyzerRunResult:
        state = load_agent_grid(scenario_id)
        runtime = GridToolRuntime(state)
        return run_analyzer_agent(runtime, client=self.client, model=self.model)

    def run_planner(
        self, scenario_id: AgentGridScenario = "mv_data_center_spike"
    ) -> tuple[AnalyzerRunResult, PlannerRunResult]:
        state = load_agent_grid(scenario_id)
        runtime = GridToolRuntime(state)
        analyzer_result = run_analyzer_agent(runtime, client=self.client, model=self.model)
        planner_result = run_planner_agent(
            runtime,
            analyzer_result.report,
            client=self.client,
            model=self.model,
        )
        return analyzer_result, planner_result
