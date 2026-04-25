from __future__ import annotations

import streamlit as st

from gridaware.actions import propose_grid_actions
from gridaware.scenarios import load_demo_scenario
from gridaware.simulator import simulate_action
from gridaware.workflow import run_mitigation_workflow


st.set_page_config(page_title="gridAware", page_icon="GA", layout="wide")

st.title("gridAware")
st.caption("Grid-aware mitigation loop for data center demand spikes.")

if "state" not in st.session_state:
    st.session_state.state = load_demo_scenario()

if st.button("Reset scenario"):
    st.session_state.state = load_demo_scenario()

state = st.session_state.state

score_col, violations_col = st.columns(2)
score_col.metric("Grid health score", state.grid_health_score)
violations_col.metric("Active violations", len(state.violations))

st.subheader("Current Violations")
st.dataframe([violation.model_dump() for violation in state.violations], use_container_width=True)

st.subheader("Candidate Actions")
actions = propose_grid_actions(state)
st.dataframe([action.model_dump() for action in actions], use_container_width=True)

selected = st.selectbox("Simulate action", [action.action_id for action in actions])
if st.button("Run simulation"):
    result = simulate_action(state, selected)
    st.json(result.model_dump(mode="json"))

if st.button("Run full mitigation workflow"):
    report = run_mitigation_workflow(state)
    st.session_state.state = report.final_state
    st.json(report.model_dump(mode="json"))
