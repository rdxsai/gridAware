# GridAware Two-Scenario Design Spec

This spec narrows the MVP to two operator-review scenarios:

1. `case33bw_data_center_spike_hard`
2. `case33bw_fallen_tree_pole_fault`

The goal is not to model a real utility feeder exactly. The goal is to build benchmark-based synthetic scenarios that behave like credible distribution-grid operating problems. The LLM agents reason over the scenario state; pandapower computes the electrical results.

## Shared Design Rules

- Use a known benchmark as the base network.
- Preserve a baseline network for comparison.
- Document every scenario modification.
- Keep each scenario to one clear story and one dominant grid problem.
- Let pandapower compute all before/after measurements.
- Keep backend validation deterministic.
- Show failed or partial actions honestly.
- Label scenarios as benchmark-based synthetic stress tests.

## Common Agent/Tool Contract

The same agent workflow should work for both scenarios:

```text
load scenario
  -> analyzer diagnoses current grid state
  -> planner proposes ranked action sequences
  -> simulator translates supported planner concepts to backend action_intents
  -> backend validates and simulates every candidate sequence
  -> simulator reports before/after results
```

Universal tools:

- `get_grid_state()`
- `get_available_controls()`
- `validate_action_intent(action_intent)`
- `simulate_candidate_sequences(candidates)`

Simulation rule:

- Inside one candidate, actions are cumulative.
- Across candidates, each candidate starts from the same original stressed grid state.

## Scenario 1: Data Center Demand Spike

### Scenario ID

`case33bw_data_center_spike_hard`

### Real-World Story

A large AI workload starts at a downstream data center. The data center sits near the tail of a radial distribution feeder. The feeder corridor serving that tail section is constrained because of thermal derating, maintenance, or a weak overhead segment. The spike increases feeder current and creates a low-voltage condition near the data center.

Operator objective:

- Reduce the constrained feeder loading below `100%`.
- Restore DC_A voltage to at least `0.95 pu`.
- Avoid creating new overloads or voltage violations.
- Prefer local support and flexible-load actions before hard curtailment when possible.

### Base Grid

Use:

```python
pandapower.networks.case33bw()
```

Interpretation:

- Radial distribution feeder.
- One substation/source at the feeder head.
- Multiple downstream load buses.
- Tail feeder section represents a weak service corridor.

### Current Implemented Scenario Modifications

Keep the current hard scenario as the reference:

- Start from `pandapower.networks.case33bw()`.
- Set substation voltage setpoint to `1.04 pu`.
- Set active feeder line ampacity to `0.40 kA`.
- Add `DC_A` at bus `32`.
- Set `DC_A` load to `0.75 MW / 0.2625 MVAr`.
- Set `DC_A.flexible_mw = 0.25`.
- Set `DC_A.max_load_mw = 0.90`.
- Add `DC_B` at bus `21`.
- Set `DC_B` load to `0.35 MW / 0.112 MVAr`.
- Set `DC_B.flexible_mw = 0.10`.
- Set `DC_B.max_load_mw = 0.70`.
- Add `BAT_A` in `feeder_tail` with `0.25 MW` available.
- Add `GEN_A` in `feeder_tail` with `0.25 MW` headroom.
- Add `VAR_A` at bus `32` with `0.10 MVAr` available.
- Derate `line_25` to `0.08 kA`.

Expected stressed-state symptoms from current implementation:

- `line_25` overloaded around `127%`.
- `DC_A` voltage around `0.914 pu`.
- Grid health score around `8`.

### Grid Elements Exposed To Agents

```json
{
  "buses": ["SUBSTATION", "DC_A", "DC_B"],
  "lines": ["line_1", "line_2", "line_25", "..."],
  "data_centers": [
    {
      "id": "DC_A",
      "zone": "feeder_tail",
      "load_mw": 0.75,
      "flexible_mw": 0.25,
      "max_load_mw": 0.90
    },
    {
      "id": "DC_B",
      "zone": "mid_feeder",
      "load_mw": 0.35,
      "flexible_mw": 0.10,
      "max_load_mw": 0.70
    }
  ],
  "batteries": [
    {
      "id": "BAT_A",
      "zone": "feeder_tail",
      "available_mw": 0.25
    }
  ],
  "local_generators": [
    {
      "id": "GEN_A",
      "zone": "feeder_tail",
      "available_headroom_mw": 0.25
    }
  ],
  "reactive_resources": [
    {
      "id": "VAR_A",
      "zone": "feeder_tail",
      "available_mvar": 0.10
    }
  ]
}
```

### Supported Action Types

```json
[
  "shift_data_center_load",
  "curtail_flexible_load",
  "dispatch_battery",
  "increase_local_generation",
  "adjust_reactive_support"
]
```

### Required Backend Checks

For `shift_data_center_load`:

- `from_dc` exists.
- `to_dc` exists.
- `from_dc != to_dc`.
- `mw > 0`.
- `mw <= from_dc.flexible_mw`.
- `mw <= to_dc.receiving_headroom_mw`.

For `curtail_flexible_load`:

- `dc` exists.
- `mw > 0`.
- `mw <= dc.flexible_mw`.

For `dispatch_battery`:

- `battery_id` exists.
- `target_dc` exists.
- `mw > 0`.
- `mw <= battery.available_mw`.
- Battery zone supports target zone.

For `increase_local_generation`:

- `generator_id` exists.
- `target_dc` exists.
- `mw > 0`.
- `mw <= generator.available_headroom_mw`.
- Generator zone supports target zone.

For `adjust_reactive_support`:

- `resource_id` exists.
- `target_bus` exists.
- `q_mvar > 0`.
- `q_mvar <= resource.available_mvar`.
- Reactive resource zone supports target bus zone.

### Expected Good Planner Behavior

Strong candidates should combine real-power and voltage-support controls, for example:

```json
{
  "candidate_id": "candidate_1",
  "action_intents": [
    {
      "type": "adjust_reactive_support",
      "resource_id": "VAR_A",
      "target_bus": "DC_A",
      "q_mvar": 0.10
    },
    {
      "type": "increase_local_generation",
      "generator_id": "GEN_A",
      "target_dc": "DC_A",
      "mw": 0.25
    },
    {
      "type": "dispatch_battery",
      "battery_id": "BAT_A",
      "target_dc": "DC_A",
      "mw": 0.25
    },
    {
      "type": "curtail_flexible_load",
      "dc": "DC_A",
      "mw": 0.25
    }
  ]
}
```

### Success Criteria

A simulated sequence is successful if:

- `line_25.loading_percent <= 100`.
- `DC_A.vm_pu >= 0.95`.
- No new overloads are created.
- No new low-voltage or high-voltage violations are created.
- Grid health score improves.

Partial improvement is acceptable but should be reported as partial, not successful.

## Scenario 2: Fallen Tree On Pole

### Scenario ID

`case33bw_fallen_tree_pole_fault`

### Real-World Story

A tree falls onto an overhead distribution pole and damages the conductor on a radial feeder segment. Protection opens the upstream device. A downstream section loses supply. The operator needs to isolate the damaged line section and restore as much downstream load as possible through an alternate normally-open tie, without overloading the alternate path.

This represents a common self-healing distribution-grid use case:

- detect fault/outage
- isolate damaged section
- close a tie switch
- restore downstream load
- verify no overloads or voltage violations after reconfiguration

Operator objective:

- Keep the faulted segment isolated.
- Restore maximum safe load downstream.
- Keep all energized line loadings below `100%`.
- Keep energized bus voltages above `0.95 pu`.
- Do not energize the faulted line.

### Base Grid

Use:

```python
pandapower.networks.case33bw()
```

Why:

- It is radial and easy to explain visually.
- It can represent a distribution feeder with sectionalizing points.
- It can be modified with switches and normally-open ties for restoration logic.

### Proposed Physical Layout

Use the feeder as a radial overhead circuit:

```text
SUBSTATION
  |
line_1
  |
main feeder
  |
line_7 / pole P7  <-- fallen tree fault
  |
downstream lateral / load pocket
  |
critical load section + optional DC_A

normally-open tie from alternate branch
  |
alternate source path
```

Recommended semantic zones:

- `feeder_head`: substation and upstream feeder.
- `fault_zone`: pole and line section damaged by tree.
- `downstream_outage_zone`: load pocket downstream of the fault.
- `alternate_feeder_zone`: neighboring feeder branch used for restoration.

### Proposed Scenario Modifications

Start from a clean `case33bw` baseline:

- Add line and switch metadata for a faulted overhead section.
- Choose one line as the damaged segment, for example `line_7`.
- Label its physical asset as `POLE_P7_TREE_FAULT`.
- Set the faulted line out of service or open isolation switches around it.
- Add an upstream sectionalizing switch, for example `SW_UP_P7`.
- Add a downstream sectionalizing switch, for example `SW_DOWN_P7`.
- Add a normally-open tie switch, for example `SW_TIE_ALT_1`.
- Add an alternate tie line connecting the downstream load pocket to another energized branch.
- Mark downstream loads as initially unserved after the fault.
- Optionally mark one downstream critical load as `CRIT_A`.
- Optionally place `DC_A` downstream to keep the data-center narrative visible, but this scenario should not depend on data-center controls.

Important: do not fake restoration results. Switching actions must modify pandapower topology and then run power flow.

### Initial Fault State

The stressed state should include:

```json
{
  "outages": [
    {
      "type": "line_fault",
      "element_id": "line_7",
      "physical_asset": "POLE_P7_TREE_FAULT",
      "status": "faulted",
      "cause": "fallen_tree_on_pole"
    },
    {
      "type": "unserved_load",
      "element_id": "downstream_section_P7",
      "unserved_load_mw": 0.6
    }
  ],
  "switch_states": [
    {
      "id": "SW_UP_P7",
      "state": "open",
      "purpose": "upstream fault isolation"
    },
    {
      "id": "SW_DOWN_P7",
      "state": "open",
      "purpose": "downstream fault isolation"
    },
    {
      "id": "SW_TIE_ALT_1",
      "state": "open",
      "purpose": "normally-open restoration tie"
    }
  ]
}
```

### Grid Elements Exposed To Agents

```json
{
  "faults": [
    {
      "id": "FAULT_TREE_P7",
      "faulted_element_id": "line_7",
      "faulted_asset": "POLE_P7_TREE_FAULT",
      "is_isolated": false
    }
  ],
  "switches": [
    {
      "id": "SW_UP_P7",
      "type": "sectionalizer",
      "state": "closed",
      "connects": ["bus_7", "line_7"]
    },
    {
      "id": "SW_DOWN_P7",
      "type": "sectionalizer",
      "state": "closed",
      "connects": ["line_7", "bus_8"]
    },
    {
      "id": "SW_TIE_ALT_1",
      "type": "normally_open_tie",
      "state": "open",
      "connects": ["alternate_branch_bus", "downstream_section_bus"]
    }
  ],
  "load_sections": [
    {
      "id": "SECTION_DOWNSTREAM_P7",
      "zone": "downstream_outage_zone",
      "served": false,
      "load_mw": 0.6,
      "critical_load_mw": 0.2
    }
  ]
}
```

### Supported Action Types

```json
[
  "open_switch",
  "close_switch",
  "isolate_faulted_line",
  "restore_load_section"
]
```

These can be represented as semantic operator actions. The backend should translate them into pandapower switch and topology mutations.

### Required Backend Checks

For `open_switch`:

- `switch_id` exists.
- Switch is controllable.
- Switch is not already open.
- Opening the switch does not disconnect protected upstream supply unexpectedly unless it is part of a fault-isolation sequence.

For `close_switch`:

- `switch_id` exists.
- Switch is controllable.
- Switch is not already closed.
- Closing the switch does not energize a faulted line.
- Closing the switch does not create an unintended loop unless looped operation is explicitly allowed.
- Post-close power flow converges.
- Post-close line loadings stay below limits.
- Post-close bus voltages stay within limits.

For `isolate_faulted_line`:

- `fault_id` exists.
- Faulted line exists.
- Required upstream and downstream isolation switches exist.
- Isolation plan opens all switches needed to de-energize the faulted line.
- Faulted line remains out of service after the action.

For `restore_load_section`:

- `section_id` exists.
- Section is currently unserved.
- Faulted line feeding the section is isolated.
- A safe alternate path or source exists.
- Required tie switch exists.
- Tie switch can be closed without energizing the faulted line.
- Post-restoration power flow converges.
- No new overloads or voltage violations are created.

### Expected Good Planner Behavior

The planner should not jump directly to closing the tie unless the fault is isolated first.

Good sequence:

```json
{
  "candidate_id": "candidate_1",
  "action_intents": [
    {
      "type": "isolate_faulted_line",
      "fault_id": "FAULT_TREE_P7",
      "line_id": "line_7",
      "open_switch_ids": ["SW_UP_P7", "SW_DOWN_P7"]
    },
    {
      "type": "restore_load_section",
      "section_id": "SECTION_DOWNSTREAM_P7",
      "close_switch_id": "SW_TIE_ALT_1"
    }
  ]
}
```

Bad sequence:

```json
{
  "candidate_id": "bad_candidate",
  "action_intents": [
    {
      "type": "close_switch",
      "switch_id": "SW_TIE_ALT_1"
    }
  ]
}
```

Why bad:

- It may backfeed the faulted segment.
- It does not prove isolation.
- It skips safety checks.

### Success Criteria

A simulated restoration sequence is successful if:

- Faulted line remains isolated.
- Downstream section is restored through the alternate path.
- Restored load MW increases.
- Unserved critical load MW decreases.
- No energized line exceeds `100%`.
- No energized bus voltage falls below `0.95 pu`.
- No new violations are created.
- Grid health score improves.

Partial success is possible:

- Fault isolated but load not restored.
- Some load restored but critical load remains unserved.
- Restoration succeeds electrically but overloads the alternate path.

These cases must be reported explicitly.

## Required Data Model Additions For Scenario 2

The current data-center scenario mostly uses:

- `data_centers`
- `batteries`
- `local_generators`
- `reactive_resources`
- `line_loadings`
- `bus_voltages`
- `violations`

The fallen-tree scenario needs additional state:

```json
{
  "faults": [],
  "switches": [],
  "load_sections": [],
  "outages": [],
  "restoration_paths": []
}
```

Recommended model concepts:

- `Fault`
- `Switch`
- `LoadSection`
- `Outage`
- `RestorationPath`

## Required Tool/Action Additions

No new top-level tool names are required immediately if `simulate_candidate_sequences` remains generic.

Required action types to add:

```json
[
  "open_switch",
  "close_switch",
  "isolate_faulted_line",
  "restore_load_section"
]
```

Required action intent fields:

```json
{
  "switch_id": "SW_TIE_ALT_1",
  "switch_ids": ["SW_UP_P7", "SW_DOWN_P7"],
  "fault_id": "FAULT_TREE_P7",
  "line_id": "line_7",
  "section_id": "SECTION_DOWNSTREAM_P7",
  "close_switch_id": "SW_TIE_ALT_1"
}
```

The simulator adapter should support conceptual aliases:

```json
{
  "isolate_fault": "isolate_faulted_line",
  "open_sectionalizer": "open_switch",
  "close_tie_switch": "close_switch",
  "reroute_power": "restore_load_section",
  "restore_downstream_load": "restore_load_section"
}
```

## MVP Boundary

For now, do not build:

- optimal power flow
- protection relay timing
- short-circuit current calculations
- crew dispatch optimization
- probabilistic outage restoration
- N-1 contingency analysis

For the MVP, the simulator only needs:

- switch state mutation
- line in-service mutation
- load served/unserved mutation
- pandapower power flow
- before/after comparison
- deterministic safety validation

## Demo Positioning

Data-center spike demonstrates:

- high-load stress
- flexible demand
- storage/generation/reactive support
- cumulative action sequences

Fallen-tree pole fault demonstrates:

- self-healing grid logic
- switching/rerouting
- fault isolation safety
- restoration tradeoffs

Together, these two scenarios show that GridAware is not hardcoded to data centers. It is a scenario-aware operator-support loop over grid states, controls, validation, and simulation.
