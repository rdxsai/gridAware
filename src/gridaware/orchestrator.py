from __future__ import annotations

from gridaware.agents.analyzer import run_analyzer_agent
from gridaware.agents.models import AnalyzerRunResult, PlannerRunResult, SimulatorRunResult
from gridaware.agents.planner import run_planner_agent
from gridaware.agents.responses_runner import DEFAULT_AGENT_MODEL, ResponsesClient
from gridaware.agents.simulator import run_simulator_agent
from gridaware.scenarios import AgentGridScenario, load_agent_scenario
from gridaware.tool_executor import GridToolRuntime


class GridOrchestrator:
    """Deterministic workflow controller for gridAware agent runs."""

    def __init__(self, *, client: ResponsesClient | None = None, model: str = DEFAULT_AGENT_MODEL) -> None:
        self.client = client
        self.model = model

    def run_analyzer(
        self, scenario_id: AgentGridScenario = "mv_data_center_spike"
    ) -> AnalyzerRunResult:
        bundle = load_agent_scenario(scenario_id)
        runtime = GridToolRuntime(scenario_bundle=bundle)
        return run_analyzer_agent(runtime, client=self.client, model=self.model)

    def run_planner(
        self, scenario_id: AgentGridScenario = "mv_data_center_spike"
    ) -> tuple[AnalyzerRunResult, PlannerRunResult]:
        bundle = load_agent_scenario(scenario_id)
        runtime = GridToolRuntime(scenario_bundle=bundle)
        analyzer_result = run_analyzer_agent(runtime, client=self.client, model=self.model)
        planner_result = run_planner_agent(
            runtime,
            analyzer_result.report,
            client=self.client,
            model=self.model,
        )
        return analyzer_result, planner_result

    def run_simulator(
        self, scenario_id: AgentGridScenario = "mv_data_center_spike"
    ) -> tuple[AnalyzerRunResult, PlannerRunResult, SimulatorRunResult]:
        bundle = load_agent_scenario(scenario_id)
        runtime = GridToolRuntime(scenario_bundle=bundle)
        analyzer_result = run_analyzer_agent(runtime, client=self.client, model=self.model)
        planner_result = run_planner_agent(
            runtime,
            analyzer_result.report,
            client=self.client,
            model=self.model,
        )
        simulator_result = run_simulator_agent(
            runtime,
            planner_result.report,
            client=self.client,
            model=self.model,
        )
        return analyzer_result, planner_result, simulator_result
