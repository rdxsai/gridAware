from __future__ import annotations

from gridaware.agents.analyzer import run_analyzer_agent
from gridaware.agents.models import AnalyzerRunResult
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
