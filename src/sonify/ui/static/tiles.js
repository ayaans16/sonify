import { el } from "./api.js";

const WINDOW_S = 60;
const SVG_NS = "http://www.w3.org/2000/svg";

export function createTiles(root) {
  const tiles = new Map(); // signal -> {node, value, unitEl, mapped, line, history, unit}

  function ensure(signal) {
    if (tiles.has(signal)) return tiles.get(signal);
    const line = document.createElementNS(SVG_NS, "polyline");
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 120 36");
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `${signal}, last 60 seconds`);
    svg.append(line);
    const value = el("span", {}, "-");
    const unitEl = el("span", { class: "unit" });
    const mapped = el("div", { class: "mapped" });
    const node = el(
      "article",
      { class: "slot", "aria-label": signal },
      el("h3", {}, signal.replaceAll("_", " ")),
      el("div", { class: "value" }, value, unitEl),
      mapped,
      svg,
    );
    root.append(node);
    const tile = { node, value, unitEl, mapped, line, history: [], unit: "", timer: null };
    tiles.set(signal, tile);
    return tile;
  }

  function draw(tile) {
    const now = Date.now() / 1000;
    tile.history = tile.history.filter(([ts]) => now - ts <= WINDOW_S);
    if (tile.history.length < 2) { tile.line.setAttribute("points", ""); return; }
    const values = tile.history.map(([, v]) => v);
    const hi = tile.unit === "%" ? 100 : Math.max(1, ...values);
    const points = tile.history.map(([ts, v]) => {
      const x = ((ts - (now - WINDOW_S)) / WINDOW_S) * 120;
      const y = 34 - Math.min(1, Math.max(0, v / hi)) * 32;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    tile.line.setAttribute("points", points.join(" "));
  }

  function setValue(tile, v, unit) {
    tile.unit = unit || tile.unit;
    tile.value.textContent = v >= 100 ? v.toFixed(0) : v.toFixed(1);
    tile.unitEl.textContent = tile.unit;
    if (tile.unit === "%") tile.node.dataset.level = v >= 85 ? "hot" : v >= 60 ? "warn" : "ok";
  }

  return {
    reset(snapshot) {
      root.replaceChildren();
      tiles.clear();
      const labels = {};
      for (const row of snapshot.mappings) (labels[row.signal] ||= []).push(row.sound);
      const signals = new Set([...Object.keys(labels), ...Object.keys(snapshot.metrics)]);
      for (const signal of signals) {
        const tile = ensure(signal);
        tile.mapped.textContent = labels[signal] ? "♪ " + [...new Set(labels[signal])].join(", ") : "no mapped sound";
        tile.history = (snapshot.history[signal] || []).slice();
        const metric = snapshot.metrics[signal];
        if (metric) setValue(tile, metric.value, metric.unit);
        draw(tile);
      }
    },
    metric(data, ts) {
      const tile = ensure(data.signal);
      tile.history.push([ts, data.value]);
      setValue(tile, data.value, data.unit);
      draw(tile);
    },
    sound(data) {
      const tile = tiles.get(data.signal);
      if (!tile || data.suppressed) return;
      tile.node.classList.remove("fired");
      void tile.node.offsetWidth; // restart the animation
      tile.node.classList.add("fired");
      clearTimeout(tile.timer);
      tile.timer = setTimeout(() => tile.node.classList.remove("fired"), 900);
    },
  };
}
