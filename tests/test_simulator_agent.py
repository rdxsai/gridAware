import json
from types import SimpleNamespace

from gridaware.agents.models import PlannerReport
from gridaware.agents.simulator import run_simulator_agent, simulator_tools
from gridaware.scenarios import load_agent_scenario
from gridaware.tool_executor import GridToolRuntime


class FakeResponses:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return SimpleNamespace(
                id="sim_1",
                output_text="",
                output=[
                    SimpleNamespace(
                        type="function_call",
                        name="simulate_action_sequence",
                        arguments=json.dumps(
                            {
                                "action_intents": [
                                    {
                                        "type": "curtail_flexible_load",
                                        "from_dc": None,
                                        "to_dc": None,
                                        "battery_id": None,
                                        "generator_id": None,
                                        "target_dc": None,
                                        "dc": "DC_A",
                                        "mw": 8.0,
                                    }
                                ]
                            }
                        ),
                        call_id="sim_call_1",
                    )
                ],
            )
        return SimpleNamespace(
            id="sim_2",
            output_text=json.dumps(
                {
                    "scenario_id": "mv_data_center_spike",
                    "simulation_summary": "One candidate simulated successfully.",
                    "action_results": [
                        {
                            "candidate_rank": 1,
                            "action_sequence": [
                                {
                                    "type": "curtail_flexible_load",
                                    "intent_summary": "Curtail flexible load at DC_A.",
                                    "from_dc": None,
                                    "to_dc": None,
                                    "battery_id": None,
                                    "generator_id": None,
                                    "target_dc": None,
                                    "dc": "DC_A",
                                    "target_element": "DC_A",
                                    "control_asset": "DC_A",
                                    "setpoint": None,
                                    "units": "MW",
                                    "mw": 8.0,
                                }
                            ],
                            "sequence_completed": True,
                            "failed_step_index": None,
                            "power_flow_converged": True,
                            "successful_changes": ["DC_A voltage improved."],
                            "failed_changes": ["line_4 violation remains."],
                            "grid_changes_summary": "Voltage improved but not all violations cleared.",
                            "remaining_violations": ["line_4"],
                            "final_grid_health_score": 40,
                        }
                    ],
                    "best_candidate_rank": 1,
                    "final_grid_status": "Improved but still has remaining violations.",
                    "final_grid_state": {
                        "scenario_id": "mv_data_center_spike",
                        "grid_health_score": 40,
                        "remaining_violations": ["line_4"],
                        "max_line_loading_percent": 105.0,
                        "min_bus_voltage_pu": 0.96,
                    },
                }
            ),
            output=[],
        )


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


def test_simulator_agent_uses_action_sequence_tool() -> None:
    planner_report = PlannerReport.model_validate(
        {
            "scenario_id": "mv_data_center_spike",
            "planning_summary": "Test simulation.",
            "primary_objectives": ["Restore DC_A voltage."],
            "candidates": [
                {
                    "rank": 1,
                    "action_sequence": [
                        {
                            "type": "curtail_flexible_load",
                            "intent_summary": "Curtail flexible load at DC_A.",
                            "from_dc": None,
                            "to_dc": None,
                            "battery_id": None,
                            "generator_id": None,
                            "target_dc": None,
                            "dc": "DC_A",
                            "target_element": "DC_A",
                            "control_asset": "DC_A",
                            "setpoint": None,
                            "units": "MW",
                            "mw": 8.0,
                        }
                    ],
                    "validation_passed": True,
                    "validation_passed_checks": ["dc exists in data_centers: DC_A"],
                    "target_violations": ["DC_A"],
                    "feasibility_checks": ["DC_A flexible_mw supports 8 MW."],
                    "expected_effect": "Improve voltage.",
                    "rationale": "Curtailment reduces demand.",
                    "risk_notes": ["May not clear line overload."],
                    "planner_confidence": "high",
                }
            ],
            "rejected_options": [],
            "requires_simulation": True,
        }
    )
    result = run_simulator_agent(
        GridToolRuntime(scenario_bundle=load_agent_scenario()),
        planner_report,
        client=FakeClient(),
        model="test-model",
    )

    assert [tool["name"] for tool in simulator_tools()] == ["simulate_action_sequence"]
    assert result.trace.tool_calls[0].name == "simulate_action_sequence"
    assert result.report.best_candidate_rank == 1
