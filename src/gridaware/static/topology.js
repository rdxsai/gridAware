import { iconSvg } from "./icons.js";

const CANVAS_WIDTH = 1000;
const CANVAS_HEIGHT = 1000;

const DISPLAY_LABEL_MAP = {
  SLACK: "Source",
  GEN_A: "Generator",
  VAR_A: "Reactive",
  BAT_A: "Battery",
  DC_A: "DataCenter A",
  DC_B: "Partner Facility",
  line_25: "Feeder 25",
};

function displayLabel(raw) {
  if (raw == null) return raw;
  if (DISPLAY_LABEL_MAP[raw]) return DISPLAY_LABEL_MAP[raw];
  const busMatch = String(raw).match(/^Bus (\d+)$/);
  if (busMatch) return `Node ${busMatch[1]}`;
  return raw;
}

function humanize(text) {
  if (!text) return text;
  return String(text)
    .replace(/\bVAR_A\b/g, "Reactive")
    .replace(/\bBAT_A\b/g, "Battery")
    .replace(/\bGEN_A\b/g, "Generator")
    .replace(/\bDC_A\b/g, "DataCenter A")
    .replace(/\bDC_B\b/g, "Partner Facility")
    .replace(/\bline_25\b/g, "Feeder 25")
    .replace(/\bSLACK\b/g, "Source")
    .replace(/\bBus (\d+)\b/g, "Node $1");
}

const state = {
  topology: null,
  mode: "line",
  selected: null,
  viewMode: "neutral",
  violations: null,
};

const canvasCard = document.querySelector(".canvas-card");
const stage = document.querySelector("#topology-stage");
const edgeLayer = document.querySelector("#edge-layer");
const nodeLayer = document.querySelector("#node-layer");
const labelLayer = document.querySelector("#label-layer");
const detailsPanel = document.querySelector("#details-panel");
const scenarioLabel = document.querySelector("#scenario-label");

async function loadTopology() {
  const response = await fetch("/grid/topology/current");
  if (!response.ok) {
    throw new Error(`Failed to load topology: ${response.status}`);
  }
  state.topology = await response.json();
  render();
}

function render() {
  const topology = state.topology;
  scenarioLabel.textContent = topology.scenario_id;
  stage.dataset.viewMode = state.viewMode;
  edgeLayer.replaceChildren();
  nodeLayer.replaceChildren();
  labelLayer.replaceChildren();

  for (const edge of topology.edges) renderEdge(edge);
  stage.dataset.edgeCount = edgeLayer.querySelectorAll(".edge-segment").length;

  for (const node of topology.nodes) {
    renderNode(node);
    renderNodeLabel(node);
  }

  fitStage();
}

function renderEdge(edge) {
  const route = edge.details.route;
  if (!route || route.length < 2) return;

  const flagged = state.violations?.lines?.includes(edge.id);
  const violating =
    edge.loading_percent !== null && edge.loading_percent !== undefined && edge.loading_percent > 100;

  route.slice(0, -1).forEach((point, index) => {
    const next = route[index + 1];
    const segment = document.createElement("button");
    segment.type = "button";
    segment.classList.add("edge-segment");
    if (flagged) {
      segment.classList.add("has-violation");
      segment.classList.add(violating ? "is-violating" : "is-resolved");
    }
    segment.dataset.id = edge.id;
    segment.setAttribute("aria-label", edge.label);
    placeSegment(segment, point, next);
    segment.addEventListener("click", (event) => {
      event.stopPropagation();
      selectItem("edge", edge);
    });
    edgeLayer.appendChild(segment);
  });

  if (
    edge.loading_percent !== null &&
    edge.loading_percent !== undefined &&
    state.viewMode !== "neutral"
  ) {
    const start = route[0];
    const end = route.at(-1);
    const midX = (start.x + end.x) / 2;
    const midY = (start.y + end.y) / 2;
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const isVertical = Math.abs(dy) > Math.abs(dx);

    let labelX;
    let labelY1;
    let labelY2;
    if (isVertical) {
      labelX = midX - 60;
      labelY1 = midY - 18;
      labelY2 = midY + 10;
    } else {
      labelX = midX;
      labelY1 = midY + 42;
      labelY2 = midY + 72;
    }

    labelLayer.appendChild(label(labelX, labelY1, displayLabel(edge.label || edge.id), "line-label"));
    let valueClass = "line-value";
    if (flagged) valueClass += violating ? " tone-bad" : " tone-good";
    labelLayer.appendChild(label(labelX, labelY2, `${edge.loading_percent}%`, valueClass));
  }
}

function placeSegment(segment, start, end) {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const length = Math.hypot(dx, dy);
  const angle = Math.atan2(dy, dx) * (180 / Math.PI);
  Object.assign(segment.style, {
    left: `${start.x}px`,
    top: `${start.y}px`,
    width: `${length}px`,
    transform: `translateY(-50%) rotate(${angle}deg)`,
  });
}

function renderNode(node) {
  const item = document.createElement("button");
  item.type = "button";
  item.classList.add("node", node.kind);
  item.dataset.id = node.id;
  item.setAttribute("aria-label", node.label);
  item.style.left = `${node.x}px`;
  item.style.top = `${node.y}px`;
  item.addEventListener("click", (event) => {
    event.stopPropagation();
    selectItem("node", node);
  });

  if (node.kind === "bus") {
    item.classList.add("bus-node");
  } else {
    item.classList.add("asset-node");
    item.innerHTML = iconSvg(node.kind);
  }

  if (state.viewMode !== "neutral" && node.details.voltage_pu != null) {
    item.classList.add(voltageTierClass(node.details.voltage_pu));
  }

  const flagged =
    state.violations?.dcs?.includes(node.id) ||
    state.violations?.buses?.includes(node.id);
  if (flagged) {
    const violating = node.details.voltage_pu != null && node.details.voltage_pu < 0.95;
    item.classList.add("has-violation");
    item.classList.add(violating ? "is-violating" : "is-resolved");
  }

  nodeLayer.appendChild(item);
}

function voltageTierClass(voltage) {
  if (voltage < 0.95) return "voltage-bad";
  if (voltage < 0.97) return "voltage-warn";
  return "voltage-good";
}

function renderNodeLabel(node) {
  if (node.kind === "bus") {
    labelLayer.appendChild(label(node.x - 18, node.y - 28, displayLabel(node.label), "label"));
    return;
  }

  if (node.id === "bus_1") {
    labelLayer.appendChild(label(node.x - 30, node.y - 62, "Source", "label"));
    labelLayer.appendChild(label(node.x - 26, node.y - 35, "Node 1", "label"));
    return;
  }

  if (node.kind === "data_center") {
    labelLayer.appendChild(centered(node.x, node.y - 70, displayLabel(node.label), "label"));
    labelLayer.appendChild(centered(node.x, node.y - 48, displayLabel(node.bus), "sublabel"));
    labelLayer.appendChild(centered(node.x, node.y + 56, "Load", "sublabel"));
    labelLayer.appendChild(centered(node.x, node.y + 76, `${fmt(node.details.load_mw)} MW`, "label"));
    labelLayer.appendChild(centered(node.x, node.y + 102, "Voltage", "sublabel"));
    let metricClass = "metric";
    if (state.viewMode !== "neutral" && node.details.voltage_pu != null) {
      metricClass += node.details.voltage_pu < 0.95 ? " tone-bad" : " tone-good";
    }
    labelLayer.appendChild(centered(node.x, node.y + 122, `${fmt(node.details.voltage_pu)} pu`, metricClass));
    return;
  }

  const labelX = node.x + 46;
  const labelY = node.y - 25;
  labelLayer.appendChild(label(labelX, labelY, displayLabel(node.label), "label"));
  labelLayer.appendChild(label(labelX, labelY + 28, displayLabel(node.bus), "sublabel"));

  if (node.kind === "battery") {
    labelLayer.appendChild(label(labelX - 15, labelY + 64, "Available", "sublabel"));
    labelLayer.appendChild(label(labelX - 15, labelY + 92, `${fmt(node.details.available_mw)} MW`, "sublabel"));
  }

  if (node.kind === "generator") {
    labelLayer.appendChild(label(labelX, labelY + 64, "Reserve", "sublabel"));
    labelLayer.appendChild(label(labelX, labelY + 92, `${fmt(node.details.headroom_mw)} MW`, "sublabel"));
  }

  if (node.kind === "reactive_support") {
    labelLayer.appendChild(label(labelX, labelY + 64, "Available", "sublabel"));
    labelLayer.appendChild(label(labelX, labelY + 92, `${fmt(node.details.available_mvar)} MVAr`, "sublabel"));
  }
}

function label(x, y, content, className) {
  const item = document.createElement("div");
  item.className = className;
  item.style.left = `${x}px`;
  item.style.top = `${y}px`;
  item.textContent = content;
  return item;
}

function centered(x, y, content, className) {
  const item = label(x, y, content, `${className} centered`);
  return item;
}

function selectItem(type, item) {
  state.selected = { type, item };
  detailsPanel.classList.remove("hidden");
  detailsPanel.innerHTML = panelHtml(type, item);
  detailsPanel.querySelector(".close").addEventListener("click", () => {
    detailsPanel.classList.add("hidden");
  });
}

function panelHtml(type, item) {
  const rows = type === "edge" ? edgeRows(item) : nodeRows(item);
  const title = displayLabel(item.label || item.id);
  return `
    <div class="details-header">
      <div class="details-title-row">
        <h2 class="details-title">${title}</h2>
        <button class="close" aria-label="Close details">×</button>
      </div>
    </div>
    <div class="details-body">
      ${rows.map(([key, value, tone]) => `<div class="row"><span>${key}</span><strong class="${tone || ""}">${value}</strong></div>`).join("")}
    </div>
  `;
}

function edgeRows(edge) {
  const details = edge.details;
  return [
    ["From", displayLabel(details.from)],
    ["To", displayLabel(details.to)],
    ["Loading", `${fmt(details.loading_percent)}%`],
    ["Current", `${fmt(details.current_ka)} kA`],
    ["Limit", `${fmt(details.limit_ka)} kA`],
    ["Power Flow", `${fmt(details.power_flow_mw)} MW`],
    ["Loss", `${fmt(details.loss_mw)} MW`],
    ["Length", `${fmt(details.length_km)} km`],
    ["Line Type", details.line_type],
    ["Last Updated", details.last_updated],
  ];
}

function nodeRows(node) {
  const details = node.details;
  const base = [["Node", displayLabel(node.bus)]];
  if (node.kind === "data_center") {
    return [
      ...base,
      ["Load", `${fmt(details.load_mw)} MW`],
      ["Voltage", `${fmt(details.voltage_pu)} pu`],
      ["Flexible", `${fmt(details.flexible_mw)} MW`],
      ["Max Load", `${fmt(details.max_load_mw)} MW`],
      ["Zone", details.zone],
    ];
  }
  if (node.kind === "battery") return [...base, ["Available", `${fmt(details.available_mw)} MW`], ["Zone", details.zone]];
  if (node.kind === "generator") return [...base, ["Reserve", `${fmt(details.headroom_mw)} MW`], ["Zone", details.zone]];
  if (node.kind === "reactive_support") return [...base, ["Available", `${fmt(details.available_mvar)} MVAr`], ["Zone", details.zone]];
  if (node.kind === "bus" || node.kind === "slack") {
    const rows = [...base];
    if (details.voltage_pu !== undefined) {
      rows.push(["Voltage", `${fmt(details.voltage_pu)} pu`]);
    }
    if (details.role) rows.push(["Role", details.role]);
    return rows;
  }
  return [...base, ...Object.entries(details).map(([key, value]) => [title(key), value])];
}

function fitStage() {
  const scale = Math.min(canvasCard.clientWidth / CANVAS_WIDTH, canvasCard.clientHeight / CANVAS_HEIGHT);
  stage.style.transform = `translateX(-50%) scale(${scale})`;
}

function fmt(value) {
  if (value === null || value === undefined) return "N/A";
  return Number(value).toFixed(Number(value) < 1 ? 3 : 2).replace(/0+$/, "").replace(/\.$/, "");
}

function title(key) {
  return key.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

document.querySelectorAll(".mode-button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".mode-button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.mode = button.dataset.mode;
  });
});

canvasCard.addEventListener("click", () => detailsPanel.classList.add("hidden"));
window.addEventListener("resize", fitStage);
new ResizeObserver(fitStage).observe(canvasCard);
loadTopology().catch((error) => {
  scenarioLabel.textContent = "Topology unavailable";
  console.error(error);
});

// === ANALYZER PANEL =============================================
const analyzerPanel = document.querySelector("#analyzer-panel");
const analyzerBody = document.querySelector("#analyzer-body");
const analyzerChip = document.querySelector("#analyze-chip");
const analyzerClose = document.querySelector("#analyzer-close");

const ANALYZER_STEPS = [
  "Connecting to analyzer agent",
  "Reading current grid state",
  "Inspecting violations",
  "Compiling findings",
];
const FAUX_STEP_MS = 1700;
const POLL_INTERVAL_MS = 600;

const analyzer = {
  jobId: null,
  pollHandle: null,
  fauxStep: 0,
  fauxHandle: null,
  result: null,
  metrics: null,
  error: null,
};

analyzerChip.addEventListener("click", () => {
  if (analyzer.pollHandle) return;
  if (analyzerPanel.dataset.state === "complete" && !analyzerPanel.classList.contains("open")) {
    analyzerPanel.classList.add("open");
    return;
  }
  startAnalyzer();
});

analyzerClose.addEventListener("click", (event) => {
  event.stopPropagation();
  analyzerPanel.classList.remove("open");
});

analyzerPanel.addEventListener("click", (event) => event.stopPropagation());

async function startAnalyzer() {
  analyzer.jobId = null;
  analyzer.fauxStep = 0;
  analyzer.result = null;
  analyzer.error = null;
  analyzerChip.disabled = true;
  analyzerPanel.dataset.state = "running";
  analyzerPanel.classList.add("open");
  renderRunning();
  analyzer.fauxHandle = setInterval(() => {
    if (analyzer.fauxStep < ANALYZER_STEPS.length - 1) {
      analyzer.fauxStep += 1;
      renderRunning();
    }
  }, FAUX_STEP_MS);

  try {
    const response = await fetch("/grid/analyze", { method: "POST" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    analyzer.jobId = data.job_id;
    pollAnalyzer();
  } catch (error) {
    analyzer.error = error.message;
    finalizeAnalyzer({ failed: true });
  }
}

function pollAnalyzer() {
  analyzer.pollHandle = setInterval(async () => {
    try {
      const response = await fetch(`/grid/analyze/${analyzer.jobId}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (data.status === "complete") {
        analyzer.result = data.report;
        analyzer.metrics = {
          grid_health_score: data.grid_health_score,
          max_line_loading_percent: data.max_line_loading_percent,
          min_bus_voltage_pu: data.min_bus_voltage_pu,
        };
        finalizeAnalyzer({ failed: false });
      } else if (data.status === "failed") {
        analyzer.error = data.error || "Analyzer failed";
        finalizeAnalyzer({ failed: true });
      }
    } catch (error) {
      analyzer.error = error.message;
      finalizeAnalyzer({ failed: true });
    }
  }, POLL_INTERVAL_MS);
}

function finalizeAnalyzer({ failed }) {
  if (analyzer.pollHandle) {
    clearInterval(analyzer.pollHandle);
    analyzer.pollHandle = null;
  }
  if (analyzer.fauxHandle) {
    clearInterval(analyzer.fauxHandle);
    analyzer.fauxHandle = null;
  }
  analyzer.fauxStep = ANALYZER_STEPS.length;
  analyzerChip.disabled = false;
  if (failed) {
    analyzerPanel.dataset.state = "failed";
    renderFailed();
  } else {
    analyzerPanel.dataset.state = "complete";
    state.violations = {
      lines: analyzer.result.violating_lines || [],
      buses: analyzer.result.violating_buses || [],
      dcs: analyzer.result.violating_data_centers || [],
    };
    state.viewMode = "analyzed";
    render();
    renderComplete();
  }
}

function renderRunning() {
  analyzerBody.className = "analyzer-body analyzer-running";
  const list = document.createElement("ul");
  list.className = "step-list";
  ANALYZER_STEPS.forEach((stepLabel, index) => {
    const row = document.createElement("li");
    let cls = "pending";
    if (index < analyzer.fauxStep) cls = "done";
    if (index === analyzer.fauxStep) cls = "active";
    row.className = `step-row ${cls}`;
    row.innerHTML = `
      <span class="idx">${String(index + 1).padStart(2, "0")}</span>
      <span class="glyph"></span>
      <span class="label">${stepLabel}</span>
    `;
    list.appendChild(row);
  });
  analyzerBody.replaceChildren(list);
}

function renderComplete() {
  const r = analyzer.result;
  analyzerBody.className = "analyzer-body analyzer-complete";

  const banner = document.createElement("div");
  banner.className = "risk-banner";
  banner.dataset.tier = r.risk_level;
  const health = analyzer.metrics?.grid_health_score;
  banner.innerHTML = `
    <span class="risk-label">Risk</span>
    <span class="risk-value">${r.risk_level.toUpperCase()}</span>
    ${
      health != null
        ? `<span class="risk-health">Health <strong>${health}</strong> / 100</span>`
        : ""
    }
  `;

  const summary = document.createElement("p");
  summary.className = "summary";
  summary.textContent = humanize(r.summary);

  const findingsCount = r.active_violations.length;
  const watchCount =
    r.watchlist_lines.length + r.watchlist_buses.length + r.watchlist_data_centers.length;

  const meta = document.createElement("div");
  meta.className = "findings-meta";
  meta.textContent =
    `Active violations · ${findingsCount}` + (watchCount ? ` · ${watchCount} watch` : "");

  const cards = document.createElement("div");
  r.active_violations.forEach((finding, i) => cards.appendChild(renderFinding(finding, i)));

  const cta = document.createElement("button");
  cta.className = "find-actions-cta";
  cta.id = "find-actions-cta";
  cta.type = "button";
  cta.textContent = "Find actions";
  cta.addEventListener("click", startPlanner);

  analyzerBody.replaceChildren(banner, summary, meta, cards, cta);
}

function renderFinding(f, i) {
  const card = document.createElement("article");
  card.className = "finding";
  card.dataset.severity = f.severity;
  card.dataset.elementId = f.element_id;
  card.style.setProperty("--i", i);
  card.innerHTML = `
    <header class="finding-head">
      <span class="severity-chip">${f.severity.toUpperCase()}</span>
      <span class="finding-type">${f.type.replaceAll("_", " ")}</span>
      <span class="finding-id">${displayLabel(f.element_id)}</span>
    </header>
    <p class="finding-explain"></p>
    <div class="finding-metrics">
      <div><span>Observed</span><strong>${fmtMetric(f.observed, f.units)}</strong></div>
      <div><span>Limit</span><strong>${fmtMetric(f.limit, f.units)}</strong></div>
    </div>
  `;
  card.querySelector(".finding-explain").textContent = humanize(f.explanation);
  card.addEventListener("click", () => flashTopologyElement(f.element_id));
  return card;
}

function fmtMetric(value, units) {
  const digits = units === "pu" ? 3 : 1;
  return `${Number(value).toFixed(digits)} ${units}`;
}

function renderFailed() {
  analyzerBody.className = "analyzer-body";
  const block = document.createElement("div");
  block.className = "analyzer-failed";
  block.innerHTML = `<strong>Analyzer failed.</strong><br>`;
  block.appendChild(document.createTextNode(analyzer.error || "Unknown error."));
  analyzerBody.replaceChildren(block);
}

function flashTopologyElement(elementId) {
  if (!elementId) return;
  const matches = document.querySelectorAll(`[data-id="${elementId}"]`);
  matches.forEach((el) => {
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
  });
  setTimeout(() => matches.forEach((el) => el.classList.remove("flash")), 1900);
}

// === PLANNER ====================================================
const PLANNER_STEPS = [
  "Reading analyzer findings",
  "Searching action inventory",
  "Validating candidates",
  "Compiling action plan",
];
const PLANNER_FAUX_STEP_MS = 25000;
const PLANNER_POLL_MS = 1500;

const planner = {
  jobId: null,
  pollHandle: null,
  fauxStep: 0,
  fauxHandle: null,
  result: null,
  error: null,
};

async function startPlanner() {
  if (planner.pollHandle) return;
  if (!analyzer.jobId || analyzerPanel.dataset.state !== "complete") return;

  planner.jobId = null;
  planner.fauxStep = 0;
  planner.result = null;
  planner.error = null;

  const cta = document.querySelector("#find-actions-cta");
  if (cta) cta.disabled = true;

  analyzerPanel.dataset.state = "planning";
  appendPlannerSection(renderPlannerRunning());

  planner.fauxHandle = setInterval(() => {
    if (planner.fauxStep < PLANNER_STEPS.length - 1) {
      planner.fauxStep += 1;
      replacePlannerSection(renderPlannerRunning());
    }
  }, PLANNER_FAUX_STEP_MS);

  try {
    const response = await fetch("/grid/plan", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ analyzer_job_id: analyzer.jobId }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    planner.jobId = data.plan_job_id;
    pollPlanner();
  } catch (error) {
    planner.error = error.message;
    finalizePlanner({ failed: true });
  }
}

function pollPlanner() {
  planner.pollHandle = setInterval(async () => {
    try {
      const response = await fetch(`/grid/plan/${planner.jobId}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (data.status === "complete") {
        planner.result = data.report;
        finalizePlanner({ failed: false });
      } else if (data.status === "failed") {
        planner.error = data.error || "Planner failed";
        finalizePlanner({ failed: true });
      }
    } catch (error) {
      planner.error = error.message;
      finalizePlanner({ failed: true });
    }
  }, PLANNER_POLL_MS);
}

function finalizePlanner({ failed }) {
  if (planner.pollHandle) {
    clearInterval(planner.pollHandle);
    planner.pollHandle = null;
  }
  if (planner.fauxHandle) {
    clearInterval(planner.fauxHandle);
    planner.fauxHandle = null;
  }
  planner.fauxStep = PLANNER_STEPS.length;

  const cta = document.querySelector("#find-actions-cta");
  if (cta) cta.remove();

  if (failed) {
    analyzerPanel.dataset.state = "failed";
    replacePlannerSection(renderPlannerFailed());
  } else {
    analyzerPanel.dataset.state = "planned";
    replacePlannerSection(renderPlannerComplete());
  }
}

function appendPlannerSection(node) {
  const cta = document.querySelector("#find-actions-cta");
  if (cta) cta.remove();

  const section = document.createElement("div");
  section.id = "planner-section";

  const divider = document.createElement("hr");
  divider.className = "planner-divider";
  section.appendChild(divider);
  section.appendChild(node);

  analyzerBody.appendChild(section);
  analyzerBody.scrollTo({ top: analyzerBody.scrollHeight, behavior: "smooth" });
}

function replacePlannerSection(node) {
  const existing = document.querySelector("#planner-section");
  if (!existing) {
    appendPlannerSection(node);
    return;
  }
  existing.replaceChildren();
  const divider = document.createElement("hr");
  divider.className = "planner-divider";
  existing.appendChild(divider);
  existing.appendChild(node);
}

function renderPlannerRunning() {
  const wrap = document.createElement("div");
  wrap.className = "analyzer-running";
  const list = document.createElement("ul");
  list.className = "step-list";
  PLANNER_STEPS.forEach((stepLabel, index) => {
    const row = document.createElement("li");
    let cls = "pending";
    if (index < planner.fauxStep) cls = "done";
    if (index === planner.fauxStep) cls = "active";
    row.className = `step-row ${cls}`;
    row.innerHTML = `
      <span class="idx">${String(index + 1).padStart(2, "0")}</span>
      <span class="glyph"></span>
      <span class="label">${stepLabel}</span>
    `;
    list.appendChild(row);
  });
  wrap.appendChild(list);
  return wrap;
}

function renderPlannerComplete() {
  const r = planner.result;
  const wrap = document.createElement("div");
  wrap.className = "analyzer-complete";

  const unique = dedupeActions(r.candidates);

  const header = document.createElement("div");
  header.className = "plan-banner";
  header.dataset.tier = "high";
  header.innerHTML = `
    <span class="plan-label">Plan</span>
    <span class="plan-value">${unique.length} ACTIONS</span>
    <span class="plan-count">available levers</span>
  `;
  wrap.appendChild(header);

  unique.forEach((action, i) => wrap.appendChild(renderActionCard(action, i)));

  const cta = document.createElement("button");
  cta.className = "execute-cta";
  cta.id = "execute-cta";
  cta.type = "button";
  cta.textContent = "Execute actions";
  cta.addEventListener("click", startExecute);
  wrap.appendChild(cta);

  return wrap;
}

function dedupeActions(candidates) {
  const seen = new Map();
  for (const candidate of candidates) {
    for (const action of candidate.action_sequence) {
      const key = [
        action.type,
        action.battery_id,
        action.generator_id,
        action.resource_id,
        action.target_dc,
        action.dc,
        action.from_dc,
        action.to_dc,
        action.target_bus,
        action.mw,
        action.q_mvar,
      ].join("|");
      if (!seen.has(key)) seen.set(key, action);
    }
  }
  return [...seen.values()];
}

function renderPlannerFailed() {
  const card = document.createElement("div");
  card.className = "agent-failure-card";
  card.innerHTML = `
    <div class="agent-failure-title">PLANNER UNAVAILABLE</div>
    <p class="agent-failure-body">
      The planner agent had trouble producing a validated plan after several attempts.
      This is usually a transient model issue.
    </p>
    <button class="agent-retry-btn" type="button">Try again</button>
  `;
  card.querySelector(".agent-retry-btn").addEventListener("click", () => {
    const section = document.querySelector("#planner-section");
    if (section) section.remove();
    analyzerPanel.dataset.state = "complete";
    startPlanner();
  });
  return card;
}

function renderActionCard(action, i) {
  const card = document.createElement("article");
  card.className = "action-card";
  card.dataset.actionType = action.type;
  card.style.setProperty("--i", i);

  const target = actionTargetLabel(action);
  const setpoint = actionSetpointLabel(action);
  const effect = actionEffectTag(action.type);

  card.innerHTML = `
    <header class="action-head">
      <span class="action-index">${String(i + 1).padStart(2, "0")}</span>
      <span class="action-type">${action.type.replaceAll("_", " ").toUpperCase()}</span>
      <span class="action-target">${humanize(target)}</span>
    </header>
    <p class="action-summary"></p>
    <div class="action-meta">
      ${setpoint ? `<span>Setpoint · <strong>${setpoint}</strong></span>` : ""}
      <span>Effect · <strong>${effect}</strong></span>
    </div>
  `;
  card.querySelector(".action-summary").textContent = humanize(
    action.intent_summary || "Planner-selected control action.",
  );

  card.addEventListener("click", () => {
    actionFlashIds(action).forEach((id) => flashTopologyElement(id));
  });
  return card;
}

function actionEffectTag(type) {
  switch (type) {
    case "adjust_reactive_support":
      return "Voltage support";
    case "dispatch_battery":
      return "Voltage + thermal relief";
    case "increase_local_generation":
      return "Voltage + thermal relief";
    case "shift_data_center_load":
      return "Thermal relief";
    case "curtail_flexible_load":
      return "Thermal relief";
    default:
      return "Mitigation";
  }
}

function actionTargetLabel(action) {
  switch (action.type) {
    case "shift_data_center_load":
      return `${displayLabel(action.from_dc) || "?"} → ${displayLabel(action.to_dc) || "?"}`;
    case "dispatch_battery":
      return displayLabel(action.battery_id) || "battery";
    case "increase_local_generation":
      return displayLabel(action.generator_id) || "generator";
    case "curtail_flexible_load":
      return displayLabel(action.target_dc) || displayLabel(action.dc) || "data center";
    case "adjust_reactive_support":
      return displayLabel(action.resource_id) || displayLabel(action.target_bus) || "Reactive";
    default:
      return "—";
  }
}

function actionSetpointLabel(action) {
  if (action.type === "adjust_reactive_support" && action.q_mvar != null) {
    return `${Number(action.q_mvar).toFixed(2)} MVAr`;
  }
  if (action.mw != null) return `${Number(action.mw).toFixed(2)} MW`;
  if (action.setpoint != null && action.units) {
    return `${Number(action.setpoint).toFixed(2)} ${action.units}`;
  }
  return null;
}

function actionFlashIds(action) {
  switch (action.type) {
    case "shift_data_center_load":
      return [action.from_dc, action.to_dc].filter(Boolean);
    case "dispatch_battery":
      return [action.battery_id].filter(Boolean);
    case "increase_local_generation":
      return [action.generator_id].filter(Boolean);
    case "curtail_flexible_load":
      return [action.target_dc || action.dc].filter(Boolean);
    case "adjust_reactive_support":
      return [action.resource_id, action.target_bus].filter(Boolean);
    default:
      return [];
  }
}

// === EXECUTOR ===================================================
const EXECUTE_STEPS = [
  "Cloning grid into sandbox",
  "Applying action sequence",
  "Re-running power flow",
  "Computing impact",
];
const EXECUTE_FAUX_STEP_MS = 1500;
const EXECUTE_POLL_MS = 500;

const executor = {
  jobId: null,
  pollHandle: null,
  fauxStep: 0,
  fauxHandle: null,
  result: null,
  error: null,
  originalTopology: null,
};

async function startExecute() {
  if (executor.pollHandle) return;
  if (!planner.jobId || !planner.result) return;

  executor.jobId = null;
  executor.fauxStep = 0;
  executor.result = null;
  executor.error = null;
  executor.originalTopology = state.topology;

  const cta = document.querySelector("#execute-cta");
  if (cta) cta.disabled = true;

  analyzerPanel.dataset.state = "executing";
  appendExecuteSection(renderExecuteRunning());

  executor.fauxHandle = setInterval(() => {
    if (executor.fauxStep < EXECUTE_STEPS.length - 1) {
      executor.fauxStep += 1;
      replaceExecuteSection(renderExecuteRunning());
    }
  }, EXECUTE_FAUX_STEP_MS);

  try {
    const response = await fetch("/grid/execute", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ plan_job_id: planner.jobId }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    executor.jobId = data.execute_job_id;
    pollExecute();
  } catch (error) {
    executor.error = error.message;
    finalizeExecute({ failed: true });
  }
}

function pollExecute() {
  executor.pollHandle = setInterval(async () => {
    try {
      const response = await fetch(`/grid/execute/${executor.jobId}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (data.status === "complete") {
        executor.result = data.report;
        finalizeExecute({ failed: false });
      } else if (data.status === "failed") {
        executor.error = data.error || "Execute failed";
        finalizeExecute({ failed: true });
      }
    } catch (error) {
      executor.error = error.message;
      finalizeExecute({ failed: true });
    }
  }, EXECUTE_POLL_MS);
}

async function finalizeExecute({ failed }) {
  if (executor.pollHandle) {
    clearInterval(executor.pollHandle);
    executor.pollHandle = null;
  }
  if (executor.fauxHandle) {
    clearInterval(executor.fauxHandle);
    executor.fauxHandle = null;
  }
  executor.fauxStep = EXECUTE_STEPS.length;

  const cta = document.querySelector("#execute-cta");
  if (cta) cta.remove();

  if (failed) {
    analyzerPanel.dataset.state = "failed";
    replaceExecuteSection(renderExecuteFailed());
    return;
  }

  analyzerPanel.dataset.state = "executed";
  replaceExecuteSection(renderExecuteComplete());

  try {
    const response = await fetch(`/grid/topology/post-action/${executor.jobId}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.topology = await response.json();
    state.viewMode = "executed";
    render();
    flashAllElements();
  } catch (error) {
    console.error("Failed to fetch post-action topology", error);
  }
}

function appendExecuteSection(node) {
  const section = document.createElement("div");
  section.id = "executor-section";

  const divider = document.createElement("hr");
  divider.className = "planner-divider";
  section.appendChild(divider);
  section.appendChild(node);

  analyzerBody.appendChild(section);
  analyzerBody.scrollTo({ top: analyzerBody.scrollHeight, behavior: "smooth" });
}

function replaceExecuteSection(node) {
  const existing = document.querySelector("#executor-section");
  if (!existing) {
    appendExecuteSection(node);
    return;
  }
  existing.replaceChildren();
  const divider = document.createElement("hr");
  divider.className = "planner-divider";
  existing.appendChild(divider);
  existing.appendChild(node);
  analyzerBody.scrollTo({ top: analyzerBody.scrollHeight, behavior: "smooth" });
}

function renderExecuteRunning() {
  const wrap = document.createElement("div");
  wrap.className = "analyzer-running";
  const list = document.createElement("ul");
  list.className = "step-list";
  EXECUTE_STEPS.forEach((stepLabel, index) => {
    const row = document.createElement("li");
    let cls = "pending";
    if (index < executor.fauxStep) cls = "done";
    if (index === executor.fauxStep) cls = "active";
    row.className = `step-row ${cls}`;
    row.innerHTML = `
      <span class="idx">${String(index + 1).padStart(2, "0")}</span>
      <span class="glyph"></span>
      <span class="label">${stepLabel}</span>
    `;
    list.appendChild(row);
  });
  wrap.appendChild(list);
  return wrap;
}

function renderExecuteComplete() {
  const r = executor.result;
  const wrap = document.createElement("div");
  wrap.className = "analyzer-complete";

  const banner = document.createElement("div");
  banner.className = "execute-banner";
  banner.dataset.success = r.all_succeeded ? "true" : "partial";
  banner.innerHTML = `
    <span class="plan-label">Execution</span>
    <span class="plan-value">${r.all_succeeded ? "ALL APPLIED" : "PARTIAL"}</span>
    <span class="plan-count">${r.actions_executed.filter((a) => a.applied).length} / ${
      r.actions_executed.length
    }</span>
  `;
  wrap.appendChild(banner);

  const metrics = document.createElement("div");
  metrics.className = "metric-grid";
  metrics.appendChild(metricRow("Grid health", r.metrics_before.grid_health_score, r.metrics_after.grid_health_score, "up"));
  metrics.appendChild(metricRow("Max line loading", r.metrics_before.max_line_loading_percent, r.metrics_after.max_line_loading_percent, "down", "%"));
  metrics.appendChild(metricRow("Min bus voltage", r.metrics_before.min_bus_voltage_pu, r.metrics_after.min_bus_voltage_pu, "up", " pu"));
  metrics.appendChild(metricRow("Active violations", r.metrics_before.active_violations, r.metrics_after.active_violations, "down"));
  wrap.appendChild(metrics);

  const summary = document.createElement("p");
  summary.className = "plan-summary";
  summary.textContent = humanize(r.summary);
  wrap.appendChild(summary);

  const actionsHeader = document.createElement("div");
  actionsHeader.className = "findings-meta";
  actionsHeader.textContent = "Actions executed";
  wrap.appendChild(actionsHeader);

  r.actions_executed.forEach((action, i) => {
    wrap.appendChild(renderExecutedActionCard(action, i));
  });

  const reset = document.createElement("button");
  reset.className = "reset-cta";
  reset.type = "button";
  reset.textContent = "Reset grid";
  reset.addEventListener("click", resetTopology);
  wrap.appendChild(reset);

  return wrap;
}

function renderExecuteFailed() {
  const block = document.createElement("div");
  block.className = "analyzer-failed";
  block.innerHTML = `<strong>Execution failed.</strong><br>`;
  block.appendChild(document.createTextNode(executor.error || "Unknown error."));
  return block;
}

function metricRow(label, before, after, betterDir, suffix = "") {
  const div = document.createElement("div");
  div.className = "metric-row";
  let tone = "muted";
  if (after !== before) {
    if (betterDir === "up") tone = after > before ? "good" : "bad";
    else tone = after < before ? "good" : "bad";
  }
  div.innerHTML = `
    <span class="metric-label">${label}</span>
    <span class="metric-before">${formatMetric(before)}${suffix}</span>
    <span class="metric-arrow">→</span>
    <strong class="metric-after" data-tone="${tone}">${formatMetric(after)}${suffix}</strong>
  `;
  return div;
}

function formatMetric(value) {
  if (Number.isInteger(value)) return String(value);
  return Number(value).toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

function renderExecutedActionCard(action, i) {
  const card = document.createElement("article");
  card.className = "executed-card";
  card.dataset.actionType = action.type;
  card.dataset.applied = action.applied ? "true" : "false";
  card.style.setProperty("--i", i);

  const typeLabel = action.type.replaceAll("_", " ").toUpperCase();
  const setpoint = action.setpoint ? `<span class="executed-setpoint">${action.setpoint}</span>` : "";

  const deltas = [];
  if (action.loading_delta_percent != null) {
    const sign = action.loading_delta_percent <= 0 ? "good" : "bad";
    const text = `${action.loading_delta_percent > 0 ? "+" : ""}${action.loading_delta_percent.toFixed(1)}%`;
    deltas.push(`<span class="executed-delta" data-tone="${sign}">Δ load ${text}</span>`);
  }
  if (action.voltage_delta_pu != null) {
    const sign = action.voltage_delta_pu >= 0 ? "good" : "bad";
    const v = action.voltage_delta_pu;
    const text = `${v > 0 ? "+" : ""}${v.toFixed(3)} pu`;
    deltas.push(`<span class="executed-delta" data-tone="${sign}">Δ volt ${text}</span>`);
  }

  card.innerHTML = `
    <header class="executed-head">
      <span class="executed-idx">${String(i + 1).padStart(2, "0")}</span>
      <span class="executed-type">${typeLabel}</span>
      <span class="executed-target">${humanize(action.target)}</span>
      <span class="executed-glyph" data-applied="${action.applied}"></span>
    </header>
    <p class="executed-summary"></p>
    <div class="executed-meta">
      ${setpoint}
      ${deltas.join("")}
    </div>
  `;
  card.querySelector(".executed-summary").textContent = humanize(action.intent_summary);
  if (!action.applied && action.error) {
    const err = document.createElement("p");
    err.className = "executed-error";
    err.textContent = action.error;
    card.appendChild(err);
  }
  return card;
}

function flashAllElements() {
  const all = document.querySelectorAll(".node, .edge-segment");
  all.forEach((el) => {
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
  });
  setTimeout(() => all.forEach((el) => el.classList.remove("flash")), 1900);
}

async function resetTopology() {
  try {
    const response = await fetch("/grid/topology/current");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.topology = await response.json();
    state.viewMode = "neutral";
    state.violations = null;
    render();
    flashAllElements();
  } catch (error) {
    console.error("Reset failed", error);
  }
}
