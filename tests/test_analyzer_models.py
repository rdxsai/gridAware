from gridaware.agents.models import AnalyzerReport


def test_analyzer_report_schema_requires_structured_fields() -> None:
    report = AnalyzerReport.model_validate(
        {
            "scenario_id": "mv_data_center_spike",
            "summary": "High stress from line overload and low data center voltage.",
            "active_violations": [
                {
                    "type": "line_overload",
                    "element_id": "line_4",
                    "observed": 111.1,
                    "limit": 100.0,
                    "units": "percent",
                    "severity": "high",
                    "explanation": "line_4 is above its thermal loading limit.",
                }
            ],
            "violating_lines": ["line_4"],
            "violating_buses": ["DC_A"],
            "violating_data_centers": ["DC_A"],
            "watchlist_lines": [
                {
                    "element_id": "line_2",
                    "observed": 90.0,
                    "limit": 100.0,
                    "units": "percent",
                    "reason": "line_2 is near the thermal loading limit but not violating.",
                }
            ],
            "watchlist_buses": [],
            "watchlist_data_centers": [],
            "risk_level": "high",
            "planner_focus": ["Reduce line_4 loading below 100 percent."],
            "forbidden_next_steps": ["Do not apply actions without simulation."],
        }
    )

    assert report.scenario_id == "mv_data_center_spike"
    assert report.active_violations[0].severity == "high"
    assert report.violating_lines == ["line_4"]
    assert report.watchlist_lines[0].element_id == "line_2"
