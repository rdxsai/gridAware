import json
from types import SimpleNamespace

from gridaware.agents.models import PlannerReport
from gridaware.agents.simulator import (
    _simulation_candidates,
    run_simulator_agent,
    simulator_tools,
)
from gridaware.scenarios import load_agent_grid, load_agent_scenario
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
                        name="simulate_candidate_sequences",
                        arguments=json.dumps(
                            {
                                "candidates": [
                                    {
                                        "candidate_id": "candidate_1",
                                        "rank": 1,
                                        "action_intents": [
                                            {
                                                "type": "curtail_flexible_load",
                                                "from_dc": None,
                                                "to_dc": None,
                                                "battery_id": None,
                                                "generator_id": None,
                                                "target_dc": None,
                                                "dc": "DC_A",
                                                "resource_id": None,
                                                "target_bus": None,
                                                "q_mvar": None,
                                                "mw": 8.0,
                                            }
                                        ],
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
                                    "resource_id": None,
                                    "target_bus": None,
                                    "q_mvar": None,
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
            "primitive_action_inventory": [],
            "candidates": [
                {
                    "rank": 1,
                    "archetype": "minimal_candidate",
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
                            "resource_id": None,
                            "target_bus": None,
                            "q_mvar": None,
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

    assert [tool["name"] for tool in simulator_tools()] == ["simulate_candidate_sequences"]
    assert result.trace.tool_calls[0].name == "simulate_candidate_sequences"
    assert result.report.best_candidate_rank == 1
    assert result.report.action_results[0].remaining_violations == [
        "line_overload line_4 at 110.9%",
        "voltage_low DC_A at 0.921 pu",
    ]
    assert result.report.final_grid_state is not None
    assert result.report.final_grid_state.remaining_violations == [
        "line_overload line_4 at 110.9%",
        "voltage_low DC_A at 0.921 pu",
    ]


def test_simulator_translates_conceptual_generation_to_backend_action() -> None:
    planner_report = PlannerReport.model_validate(
        {
            "scenario_id": "case33bw_data_center_spike_hard",
            "planning_summary": "Use local generation near DC_A.",
            "primary_objectives": ["Reduce line_25 loading."],
            "primitive_action_inventory": [],
            "candidates": [
                {
                    "rank": 2,
                    "archetype": "minimal_candidate",
                    "action_sequence": [
                        {
                            "type": "increase_local_generation",
                            "intent_summary": "Dispatch local generation near DC_A.",
                            "from_dc": None,
                            "to_dc": None,
                            "battery_id": None,
                            "generator_id": "GEN_A",
                            "target_dc": None,
                            "dc": None,
                            "resource_id": "GEN_A",
                            "target_bus": "DC_A",
                            "q_mvar": None,
                            "target_element": None,
                            "control_asset": "GEN_A",
                            "setpoint": 0.25,
                            "units": "MW",
                            "mw": 0.25,
                        }
                    ],
                    "validation_passed": False,
                    "validation_passed_checks": [],
                    "target_violations": ["line_25"],
                    "feasibility_checks": ["GEN_A has 0.25 MW headroom."],
                    "expected_effect": "Reduce upstream imports.",
                    "rationale": "Generation near the tail should relieve the constrained corridor.",
                    "risk_notes": [],
                    "planner_confidence": "medium",
                }
            ],
            "rejected_options": [],
            "requires_simulation": True,
        }
    )

    candidates, unsupported = _simulation_candidates(planner_report)

    assert unsupported == []
    assert candidates == [
        {
            "candidate_id": "candidate_2",
            "rank": 2,
            "action_intents": [
                {
                    "type": "increase_local_generation",
                    "from_dc": None,
                    "to_dc": None,
                    "battery_id": None,
                    "generator_id": "GEN_A",
                    "target_dc": "DC_A",
                    "dc": None,
                    "resource_id": None,
                    "target_bus": None,
                    "q_mvar": None,
                    "mw": 0.25,
                }
            ],
        }
    ]


def test_simulator_translates_storage_discharge_to_battery_dispatch() -> None:
    planner_report = PlannerReport.model_validate(
        {
            "scenario_id": "case33bw_data_center_spike_hard",
            "planning_summary": "Use battery support near DC_A.",
            "primary_objectives": ["Reduce line_25 loading."],
            "primitive_action_inventory": [],
            "candidates": [
                {
                    "rank": 1,
                    "archetype": "minimal_candidate",
                    "action_sequence": [
                        {
                            "type": "dispatch_battery",
                            "intent_summary": "Discharge battery near DC_A.",
                            "from_dc": None,
                            "to_dc": "DC_A",
                            "battery_id": "BAT_A",
                            "generator_id": None,
                            "target_dc": "DC_A",
                            "dc": "DC_A",
                            "resource_id": "BAT_A",
                            "target_bus": None,
                            "q_mvar": None,
                            "target_element": None,
                            "control_asset": "BAT_A",
                            "setpoint": 0.25,
                            "units": "MW",
                            "mw": 0.25,
                        }
                    ],
                    "validation_passed": False,
                    "validation_passed_checks": [],
                    "target_violations": ["line_25"],
                    "feasibility_checks": ["BAT_A has 0.25 MW available."],
                    "expected_effect": "Reduce upstream imports.",
                    "rationale": "Battery near the tail should relieve the constrained corridor.",
                    "risk_notes": [],
                    "planner_confidence": "medium",
                }
            ],
            "rejected_options": [],
            "requires_simulation": True,
        }
    )

    candidates, unsupported = _simulation_candidates(planner_report)

    assert unsupported == []
    assert candidates[0]["action_intents"] == [
        {
            "type": "dispatch_battery",
            "from_dc": None,
            "to_dc": None,
            "battery_id": "BAT_A",
            "generator_id": None,
            "target_dc": "DC_A",
            "dc": None,
            "resource_id": None,
            "target_bus": None,
            "q_mvar": None,
            "mw": 0.25,
        }
    ]


def test_simulator_translates_adjust_battery_dispatch_alias() -> None:
    planner_report = PlannerReport.model_validate(
        {
            "scenario_id": "case33bw_data_center_spike_tricky",
            "planning_summary": "Use battery support near DC_A.",
            "primary_objectives": ["Reduce line_25 loading."],
            "primitive_action_inventory": [],
            "candidates": [
                {
                    "rank": 1,
                    "archetype": "minimal_candidate",
                    "action_sequence": [
                        {
                            "type": "dispatch_battery",
                            "intent_summary": "Discharge battery near DC_A.",
                            "from_dc": None,
                            "to_dc": None,
                            "battery_id": "BAT_A",
                            "generator_id": None,
                            "target_dc": "DC_A",
                            "dc": "DC_A",
                            "resource_id": "BAT_A",
                            "target_bus": "DC_A",
                            "q_mvar": None,
                            "target_element": None,
                            "control_asset": "BAT_A",
                            "setpoint": 0.20,
                            "units": "MW",
                            "mw": 0.20,
                        }
                    ],
                    "validation_passed": False,
                    "validation_passed_checks": [],
                    "target_violations": ["line_25"],
                    "feasibility_checks": ["BAT_A has 0.20 MW available."],
                    "expected_effect": "Reduce upstream imports.",
                    "rationale": "Battery near the tail should relieve the constrained corridor.",
                    "risk_notes": [],
                    "planner_confidence": "medium",
                }
            ],
            "rejected_options": [],
            "requires_simulation": True,
        }
    )

    candidates, unsupported = _simulation_candidates(planner_report)

    assert unsupported == []
    assert candidates[0]["action_intents"][0]["type"] == "dispatch_battery"


def test_simulator_translates_adjust_local_generation_alias() -> None:
    planner_report = PlannerReport.model_validate(
        {
            "scenario_id": "case33bw_data_center_spike_tricky",
            "planning_summary": "Use local generation near DC_A.",
            "primary_objectives": ["Reduce line_25 loading."],
            "primitive_action_inventory": [],
            "candidates": [
                {
                    "rank": 1,
                    "archetype": "minimal_candidate",
                    "action_sequence": [
                        {
                            "type": "increase_local_generation",
                            "intent_summary": "Dispatch local generation near DC_A.",
                            "from_dc": None,
                            "to_dc": None,
                            "battery_id": None,
                            "generator_id": "GEN_A",
                            "target_dc": "DC_A",
                            "dc": "DC_A",
                            "resource_id": "GEN_A",
                            "target_bus": "DC_A",
                            "q_mvar": None,
                            "target_element": None,
                            "control_asset": "GEN_A",
                            "setpoint": 0.20,
                            "units": "MW",
                            "mw": 0.20,
                        }
                    ],
                    "validation_passed": False,
                    "validation_passed_checks": [],
                    "target_violations": ["line_25"],
                    "feasibility_checks": ["GEN_A has 0.20 MW headroom."],
                    "expected_effect": "Reduce upstream imports.",
                    "rationale": "Generation near the tail should relieve the constrained corridor.",
                    "risk_notes": [],
                    "planner_confidence": "medium",
                }
            ],
            "rejected_options": [],
            "requires_simulation": True,
        }
    )

    candidates, unsupported = _simulation_candidates(planner_report)

    assert unsupported == []
    assert candidates[0]["action_intents"][0]["type"] == "increase_local_generation"


def test_simulator_translates_load_setpoint_to_curtailment_delta() -> None:
    planner_report = PlannerReport.model_validate(
        {
            "scenario_id": "case33bw_data_center_spike_tricky",
            "planning_summary": "Curtail DC_A to a lower setpoint.",
            "primary_objectives": ["Reduce line_25 loading."],
            "primitive_action_inventory": [],
            "candidates": [
                {
                    "rank": 1,
                    "archetype": "minimal_candidate",
                    "action_sequence": [
                        {
                            "type": "curtail_flexible_load",
                            "intent_summary": "Reduce DC_A load from 0.90 MW to 0.60 MW.",
                            "from_dc": None,
                            "to_dc": "DC_A",
                            "battery_id": None,
                            "generator_id": None,
                            "target_dc": "DC_A",
                            "dc": "DC_A",
                            "resource_id": None,
                            "target_bus": "DC_A",
                            "q_mvar": None,
                            "target_element": None,
                            "control_asset": None,
                            "setpoint": 0.60,
                            "units": "MW",
                            "mw": None,
                        }
                    ],
                    "validation_passed": False,
                    "validation_passed_checks": [],
                    "target_violations": ["line_25"],
                    "feasibility_checks": ["DC_A has 0.30 MW flexible load."],
                    "expected_effect": "Reduce downstream current.",
                    "rationale": "Curtailment should relieve the constrained corridor.",
                    "risk_notes": [],
                    "planner_confidence": "medium",
                }
            ],
            "rejected_options": [],
            "requires_simulation": True,
        }
    )

    candidates, unsupported = _simulation_candidates(
        planner_report, load_agent_grid("case33bw_data_center_spike_tricky")
    )

    assert unsupported == []
    assert candidates[0]["action_intents"] == [
        {
            "type": "curtail_flexible_load",
            "from_dc": None,
            "to_dc": None,
            "battery_id": None,
            "generator_id": None,
            "target_dc": None,
            "dc": "DC_A",
            "resource_id": None,
            "target_bus": None,
            "q_mvar": None,
            "mw": 0.3,
        }
    ]
