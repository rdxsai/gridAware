from __future__ import annotations

import json

from gridaware.scenarios import load_demo_scenario
from gridaware.workflow import run_mitigation_workflow


def main() -> None:
    state = load_demo_scenario()
    report = run_mitigation_workflow(state)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
