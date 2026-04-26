const CANVAS_WIDTH = 1000;
const CANVAS_HEIGHT = 860;

const state = {
  topology: null,
  mode: "line",
  selected: null,
};

const canvasCard = document.querySelector(".canvas-card");
const stage = document.querySelector("#topology-stage");
const edgeLayer = document.querySelector("#edge-layer");
const nodeLayer = document.querySelector("#node-layer");
const labelLayer = document.querySelector("#label-layer");
const detailsPanel = document.querySelector("#details-panel");
const scenarioLabel = document.querySelector("#scenario-label");
const gridHealth = document.querySelector("#grid-health");

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
  gridHealth.textContent = `Health ${topology.metrics.grid_health} · ${topology.metrics.active_violations} violations`;
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

  route.slice(0, -1).forEach((point, index) => {
    const next = route[index + 1];
    const segment = document.createElement("button");
    segment.type = "button";
    segment.classList.add("edge-segment");
    if (edge.status === "overloaded") segment.classList.add("overloaded");
    segment.dataset.id = edge.id;
    segment.setAttribute("aria-label", edge.label);
    placeSegment(segment, point, next);
    segment.addEventListener("click", (event) => {
      event.stopPropagation();
      selectItem("edge", edge);
    });
    edgeLayer.appendChild(segment);
  });

  if (edge.id === "line_25") {
    const midX = (route[0].x + route.at(-1).x) / 2;
    const midY = (route[0].y + route.at(-1).y) / 2;
    labelLayer.appendChild(label(midX, midY + 42, "line_25", "line-label"));
    labelLayer.appendChild(label(midX, midY + 72, `${edge.loading_percent}%`, "line-value"));
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
    item.textContent = nodeIcon(node);
  }

  nodeLayer.appendChild(item);
}

function renderNodeLabel(node) {
  if (node.kind === "bus") {
    labelLayer.appendChild(label(node.x - 18, node.y - 28, node.label, "label"));
    return;
  }

  if (node.id === "bus_1") {
    labelLayer.appendChild(label(node.x - 24, node.y - 62, "SLACK", "label"));
    labelLayer.appendChild(label(node.x - 22, node.y - 35, "Bus 1", "label"));
    return;
  }

  const labelX = node.kind === "data_center" ? node.x - 45 : node.x + 46;
  const labelY = node.kind === "data_center" ? node.y - 50 : node.y - 25;
  labelLayer.appendChild(label(labelX, labelY, node.label, "label"));
  labelLayer.appendChild(label(labelX, labelY + 28, node.bus, "sublabel"));

  if (node.kind === "data_center") {
    labelLayer.appendChild(label(labelX + 16, labelY + 70, "Load", "sublabel"));
    labelLayer.appendChild(label(labelX - 4, labelY + 100, `${fmt(node.details.load_mw)} MW`, "sublabel"));
    labelLayer.appendChild(label(labelX + 14, labelY + 142, "Voltage", "sublabel"));
    labelLayer.appendChild(
      label(
        labelX - 2,
        labelY + 172,
        `${fmt(node.details.voltage_pu)} pu`,
        node.details.voltage_pu < 0.95 ? "metric bad" : "metric good",
      ),
    );
  }

  if (node.kind === "battery") {
    labelLayer.appendChild(label(labelX - 15, labelY + 64, "Available", "sublabel"));
    labelLayer.appendChild(label(labelX - 15, labelY + 92, `${fmt(node.details.available_mw)} MW`, "sublabel"));
  }

  if (node.kind === "generator") {
    labelLayer.appendChild(label(labelX, labelY + 64, "Headroom", "sublabel"));
    labelLayer.appendChild(label(labelX, labelY + 92, `${fmt(node.details.headroom_mw)} MW`, "sublabel"));
  }

  if (node.kind === "reactive_support") {
    labelLayer.appendChild(label(labelX, labelY + 64, "Available", "sublabel"));
    labelLayer.appendChild(label(labelX, labelY + 92, `${fmt(node.details.available_mvar)} MVAr`, "sublabel"));
  }
}

function nodeIcon(node) {
  if (node.kind === "data_center") return "▦";
  if (node.kind === "battery") return "▣";
  if (node.kind === "generator") return "G";
  if (node.kind === "reactive_support") return "ϕ";
  if (node.kind === "slack") return "~";
  return "";
}

function label(x, y, content, className) {
  const item = document.createElement("div");
  item.className = className;
  item.style.left = `${x}px`;
  item.style.top = `${y}px`;
  item.textContent = content;
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
  const status = item.status === "overloaded" ? "Overloaded" : item.details.status || item.status;
  const rows = type === "edge" ? edgeRows(item) : nodeRows(item);
  return `
    <div class="details-header">
      <div class="details-title-row">
        <h2 class="details-title">${item.label || item.id}</h2>
        <button class="close" aria-label="Close details">×</button>
      </div>
      <div class="status">${status}</div>
    </div>
    <div class="details-body">
      ${rows.map(([key, value, tone]) => `<div class="row"><span>${key}</span><strong class="${tone || ""}">${value}</strong></div>`).join("")}
    </div>
  `;
}

function edgeRows(edge) {
  const details = edge.details;
  return [
    ["From", details.from],
    ["To", details.to],
    ["Status", details.status, "success"],
    ["Loading", `${fmt(details.loading_percent)}%`, edge.status === "overloaded" ? "danger" : ""],
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
  const base = [
    ["Bus", node.bus],
    ["Status", details.status, node.status === "violation" ? "danger" : "success"],
  ];
  if (node.kind === "data_center") {
    return [
      ...base,
      ["Load", `${fmt(details.load_mw)} MW`],
      ["Voltage", `${fmt(details.voltage_pu)} pu`, details.voltage_pu < 0.95 ? "danger" : "success"],
      ["Flexible", `${fmt(details.flexible_mw)} MW`],
      ["Max Load", `${fmt(details.max_load_mw)} MW`],
      ["Zone", details.zone],
    ];
  }
  if (node.kind === "battery") return [...base, ["Available", `${fmt(details.available_mw)} MW`], ["Zone", details.zone]];
  if (node.kind === "generator") return [...base, ["Headroom", `${fmt(details.headroom_mw)} MW`], ["Zone", details.zone]];
  if (node.kind === "reactive_support") return [...base, ["Available", `${fmt(details.available_mvar)} MVAr`], ["Zone", details.zone]];
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
loadTopology().catch((error) => {
  scenarioLabel.textContent = "Topology unavailable";
  gridHealth.textContent = error.message;
});
