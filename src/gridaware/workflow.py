from __future__ import annotations

from gridaware.actions import propose_grid_actions
from gridaware.models import GridState, WorkflowReport
from gridaware.simulator import apply_action, evaluate_result, simulate_action


def run_mitigation_workflow(state: GridState) -> WorkflowReport:
    """Run a bounded inspect-plan-simulate-evaluate-apply loop."""

    actions = propose_grid_actions(state)
    evaluations = []
    selected_action = None
    final_state = state

    for action in actions:
        result = simulate_action(state, action.action_id)
        evaluation = evaluate_result(result)
        evaluations.append(evaluation)

        if evaluation.accepted:
            selected_action = action
            final_state = apply_action(state, action.action_id).state
            break

    return WorkflowReport(
        scenario_id=state.scenario_id,
        original_score=state.grid_health_score,
        final_score=final_state.grid_health_score,
        violations_before=len(state.violations),
        violations_after=len(final_state.violations),
        selected_action=selected_action,
        evaluated_actions=evaluations,
        final_state=final_state,
    )
