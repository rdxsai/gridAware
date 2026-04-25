from gridaware.scenarios import load_demo_scenario
from gridaware.workflow import run_mitigation_workflow


def test_workflow_applies_first_safe_action() -> None:
    report = run_mitigation_workflow(load_demo_scenario())

    assert report.selected_action is not None
    assert report.selected_action.action_id == "A1"
    assert report.violations_before == 2
    assert report.violations_after == 0
    assert report.final_score > report.original_score
