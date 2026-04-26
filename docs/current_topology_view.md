# Current Topology View

The current topology view is scoped to present-state grid inspection only. It does not run agents,
simulate mitigations, or apply actions.

## Backend

- `GET /grid/topology/current`
- Default scenario: `case33bw_data_center_spike_tricky`
- Source data: `ScenarioBundle.net` plus the agent-facing `GridState`

The response contains:

- `metrics`: grid health, active violation count, voltage and loading limits
- `nodes`: clickable buses, data centers, battery, generator, reactive support, and slack source
- `edges`: clickable feeder lines, including overloaded `line_25`

## UI

- `GET /app`
- Static SVG/CSS/JS served through FastAPI
- Click any node or edge to show a details panel
- Current controls are visual only: layout, zoom, line loading, voltage, and labels

## Display Mapping

The view intentionally uses a simplified radial operator schematic instead of plotting every
case33bw bus. The topology adapter maps the current scenario to display buses:

- `DC_A -> Bus 12`
- `DC_B -> Bus 13`
- `BAT_A -> Bus 8`
- `GEN_A -> Bus 3`
- `VAR_A -> Bus 7`
- `line_25 -> Bus 12 to Bus 13`

Physics values such as voltage, line loading, current, and losses come from pandapower output when
available. Display coordinates and simplified bus labels are UI metadata.
