const state = {
  topology: null,
  mode: "line",
  selected: null,
};

const svg = document.querySelector("#topology");
const edgeLayer = document.querySelector("#edges");
const nodeLayer = document.querySelector("#nodes");
const labelLayer = document.querySelector("#labels");
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

  const nodesById = new Map(topology.nodes.map((node) => [node.id, node]));
  for (const edge of topology.edges) {
    renderEdge(edge, nodesById);
  }
  for (const node of topology.nodes) {
    renderNode(node);
    renderNodeLabel(node);
  }
}

function renderEdge(edge, nodesById) {
  const from = nodesById.get(edge.from_node);
  const to = nodesById.get(edge.to_node);
  if (!from || !to) return;

  const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
  line.setAttribute("x1", from.x);
  line.setAttribute("y1", from.y);
  line.setAttribute("x2", to.x);
  line.setAttribute("y2", to.y);
  line.classList.add("edge");
  if (edge.status === "overloaded") line.classList.add("overloaded");
  line.dataset.id = edge.id;
  line.addEventListener("click", (event) => {
    event.stopPropagation();
    selectItem("edge", edge);
  });
  edgeLayer.appendChild(line);

  if (edge.id === "line_25") {
    const midX = (from.x + to.x) / 2;
    const midY = (from.y + to.y) / 2;
    labelLayer.appendChild(text(midX, midY + 42, "line_25", "line-label"));
    labelLayer.appendChild(text(midX, midY + 72, `${edge.loading_percent}%`, "line-value"));
  }
}

function renderNode(node) {
  if (node.kind === "bus") {
    const circle = circleNode(node.x, node.y, 9, "node-core");
    circle.addEventListener("click", (event) => {
      event.stopPropagation();
      selectItem("node", node);
    });
    nodeLayer.appendChild(circle);
    return;
  }

  const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
  group.classList.add("asset");
  group.dataset.id = node.id;
  group.addEventListener("click", (event) => {
    event.stopPropagation();
    selectItem("node", node);
  });

  const ring = circleNode(node.x, node.y, node.kind === "data_center" ? 42 : 34, "asset-ring");
  ring.classList.add(node.kind);
  group.appendChild(ring);

  if (node.kind === "data_center") {
    group.appendChild(text(node.x, node.y + 2, "▦", "asset-icon"));
  } else if (node.kind === "battery") {
    group.appendChild(text(node.x, node.y, "▣", "asset-icon"));
  } else if (node.kind === "generator") {
    group.appendChild(text(node.x, node.y, "G", "asset-text"));
  } else if (node.kind === "reactive_support") {
    group.appendChild(text(node.x, node.y, "ϕ", "asset-text"));
  } else if (node.kind === "slack") {
    group.appendChild(text(node.x, node.y, "~", "asset-text"));
  }

  nodeLayer.appendChild(group);
}

function renderNodeLabel(node) {
  if (node.kind === "bus") {
    labelLayer.appendChild(text(node.x - 18, node.y - 28, node.label, "label"));
    return;
  }

  if (node.id === "bus_1") {
    labelLayer.appendChild(text(node.x - 24, node.y - 62, "SLACK", "label"));
    labelLayer.appendChild(text(node.x - 22, node.y - 35, "Bus 1", "label"));
    return;
  }

  const labelX = node.kind === "data_center" ? node.x - 45 : node.x + 46;
  const labelY = node.kind === "data_center" ? node.y - 50 : node.y - 25;
  labelLayer.appendChild(text(labelX, labelY, node.label, "label"));
  labelLayer.appendChild(text(labelX, labelY + 28, node.bus, "sublabel"));

  if (node.kind === "data_center") {
    labelLayer.appendChild(text(labelX + 16, labelY + 70, "Load", "sublabel"));
    labelLayer.appendChild(text(labelX - 4, labelY + 100, `${fmt(node.details.load_mw)} MW`, "sublabel"));
    labelLayer.appendChild(text(labelX + 14, labelY + 142, "Voltage", "sublabel"));
    labelLayer.appendChild(
      text(
        labelX - 2,
        labelY + 172,
        `${fmt(node.details.voltage_pu)} pu`,
        node.details.voltage_pu < 0.95 ? "metric bad" : "metric good",
      ),
    );
  }

  if (node.kind === "battery") {
    labelLayer.appendChild(text(labelX - 15, labelY + 64, "Available", "sublabel"));
    labelLayer.appendChild(text(labelX - 15, labelY + 92, `${fmt(node.details.available_mw)} MW`, "sublabel"));
  }

  if (node.kind === "generator") {
    labelLayer.appendChild(text(labelX, labelY + 64, "Headroom", "sublabel"));
    labelLayer.appendChild(text(labelX, labelY + 92, `${fmt(node.details.headroom_mw)} MW`, "sublabel"));
  }

  if (node.kind === "reactive_support") {
    labelLayer.appendChild(text(labelX, labelY + 64, "Available", "sublabel"));
    labelLayer.appendChild(text(labelX, labelY + 92, `${fmt(node.details.available_mvar)} MVAr`, "sublabel"));
  }
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

function circleNode(x, y, radius, className) {
  const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  circle.setAttribute("cx", x);
  circle.setAttribute("cy", y);
  circle.setAttribute("r", radius);
  circle.setAttribute("class", className);
  return circle;
}

function text(x, y, content, className) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", "text");
  node.setAttribute("x", x);
  node.setAttribute("y", y);
  node.setAttribute("class", className);
  node.textContent = content;
  return node;
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

svg.addEventListener("click", () => detailsPanel.classList.add("hidden"));
loadTopology().catch((error) => {
  scenarioLabel.textContent = "Topology unavailable";
  gridHealth.textContent = error.message;
});
