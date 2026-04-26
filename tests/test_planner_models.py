import pytest

from pydantic import ValidationError

from gridaware.agents.models import PlannerActionIntent, PlannerReport


def test_planner_report_schema_requires_ranked_action_sequences() -> None:
    report = PlannerReport.model_validate(
        {
            "scenario_id": "mv_data_center_spike",
            "planning_summary": "Prioritize reducing DC_A stress and line_4 loading.",
            "primary_objectives": [
                "Reduce line_4 loading below 100 percent.",
                "Restore DC_A voltage to at least 0.95 pu.",
            ],
            "primitive_action_inventory": [
                {
                    "action_type": "shift_data_center_load",
                    "target": "DC_A->DC_B",
                    "max_value": 10.0,
                    "units": "MW",
                    "primary_effect": "thermal_and_voltage",
                    "backend_action_intent": {
                        "type": "shift_data_center_load",
                        "from_dc": "DC_A",
                        "to_dc": "DC_B",
                        "battery_id": None,
                        "generator_id": None,
                        "target_dc": None,
                        "dc": None,
                        "resource_id": None,
                        "target_bus": None,
                        "q_mvar": None,
                        "mw": 10.0,
                    },
                    "rationale": "DC_A can move flexible load to DC_B.",
                }
            ],
            "candidates": [
                {
                    "rank": 1,
                    "archetype": "minimal_candidate",
                    "action_sequence": [
                        {
                            "type": "shift_data_center_load",
                            "intent_summary": "Shift flexible data-center load away from DC_A.",
                            "from_dc": "DC_A",
                            "to_dc": "DC_B",
                            "battery_id": None,
                            "generator_id": None,
                            "target_dc": None,
                            "dc": None,
                            "resource_id": None,
                            "target_bus": None,
                            "q_mvar": None,
                            "target_element": "DC_A",
                            "control_asset": None,
                            "setpoint": None,
                            "units": "MW",
                            "mw": 10.0,
                        }
                    ],
                    "validation_passed": True,
                    "validation_passed_checks": [
                        "from_dc exists in data_centers: DC_A",
                        "to_dc exists in data_centers: DC_B",
                    ],
                    "target_violations": ["line_4", "DC_A"],
                    "feasibility_checks": [
                        "DC_A exists with 24 MW flexible load.",
                        "DC_B has 23 MW receiving headroom.",
                    ],
                    "expected_effect": "Reduce demand at DC_A and relieve the stressed corridor.",
                    "rationale": "A partial shift addresses both active violations without maxing transfer.",
                    "risk_notes": ["Simulation must verify watchlist lines remain below limits."],
                    "planner_confidence": "high",
                }
            ],
            "rejected_options": ["Do not apply any action without simulation."],
            "requires_simulation": True,
        }
    )

    assert report.requires_simulation is True
    assert report.candidates[0].action_sequence[0].from_dc == "DC_A"
    assert report.candidates[0].planner_confidence == "high"


def test_planner_action_intent_rejects_action_aliases() -> None:
    with pytest.raises(ValidationError):
        PlannerActionIntent.model_validate(
            {
                "type": "adjust_load",
                "intent_summary": "Alias should not be accepted.",
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
                "control_asset": None,
                "setpoint": None,
                "units": "MW",
                "mw": 0.1,
            }
        )
