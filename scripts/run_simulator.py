from __future__ import annotations

import argparse
import json

from gridaware.orchestrator import GridOrchestrator


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the gridAware analyzer + planner + simulator agents."
    )
    parser.add_argument(
        "--scenario",
        default="mv_data_center_spike",
        choices=[
            "baseline_case33bw",
            "case33bw_data_center_spike",
            "case33bw_data_center_spike_hard",
            "case33bw_data_center_spike_tricky",
            "mv_data_center_spike",
            "mv_renewable_drop",
            "mv_line_constraint",
            "lv_edge_data_center",
        ],
    )
    args = parser.parse_args()

    analyzer_result, planner_result, simulator_result = GridOrchestrator().run_simulator(
        args.scenario
    )
    print(
        json.dumps(
            {
                "analyzer": analyzer_result.model_dump(mode="json"),
                "planner": planner_result.model_dump(mode="json"),
                "simulator": simulator_result.model_dump(mode="json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
