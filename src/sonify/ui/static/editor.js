import { api, el } from "./api.js";

// Path helpers: paths are dotted strings matching the server's error paths,
// e.g. "signals.cpu_percent.events.0.cooldown_s" (see config.validate_mapping).
const split = (path) => path.split(".");
function getAt(obj, path) {
  return split(path).reduce((o, k) => (o == null ? undefined : o[k]), obj);
}
function setAt(obj, path, value) {
  const keys = split(path);
  const last = keys.pop();
  const parent = keys.reduce((o, k) => o[k], obj);
  if (value === undefined) delete parent[last];
  else parent[last] = value;
}
const clone = (x) => JSON.parse(JSON.stringify(x));
const idFor = (path) => "ed-" + path.replaceAll(".", "-");

export function createEditor(form) {
  let baseline = null;
  let draft = null;
  let statusEl, summaryEl, saveBtn;

  async function load() {
    const { ok, data } = await api.getConfig();
    if (!ok) { form.replaceChildren(el("p", { class: "status bad" }, "Could not load config.")); return; }
    baseline = clone(data);
    draft = clone(data);
    render();
  }

  const dirty = () => JSON.stringify(draft) !== JSON.stringify(baseline);

  function updateDirty() {
    if (saveBtn) saveBtn.disabled = !dirty();
    if (statusEl && dirty()) { statusEl.textContent = "Unsaved changes"; statusEl.className = "status"; }
  }

  // ---- field builders -------------------------------------------------

  function clearError(path) {
    const msg = form.querySelector(`[data-err="${path}"]`);
    if (msg) msg.hidden = true;
    const input = form.querySelector(`#${idFor(path)}`);
    if (input) input.removeAttribute("aria-invalid");
  }

  function errorSlot(path) {
    return el("small", { class: "err", "data-err": path, id: idFor(path) + "-err", hidden: true, role: "alert" });
  }

  function numberField(label, path, { optional = true, step = "any", min, max } = {}) {
    const current = getAt(draft, path);
    const input = el("input", {
      id: idFor(path), type: "number", step, min, max, value: current ?? "",
      "aria-describedby": idFor(path) + "-err",
      oninput: (e) => {
        const raw = e.target.value;
        setAt(draft, path, raw === "" ? undefined : Number(raw));
        clearError(path);
        updateDirty();
      },
    });
    return el("div", { class: "field" }, el("label", { for: idFor(path) }, label), input, errorSlot(path));
  }

  function textField(label, path) {
    const input = el("input", {
      id: idFor(path), type: "text", value: getAt(draft, path) ?? "", "aria-describedby": idFor(path) + "-err",
      oninput: (e) => { setAt(draft, path, e.target.value); clearError(path); updateDirty(); },
    });
    return el("div", { class: "field" }, el("label", { for: idFor(path) }, label), input, errorSlot(path));
  }

  function selectField(label, path, options, { preview = false, rerender = false } = {}) {
    const current = getAt(draft, path);
    const values = options.includes(current) || current === undefined ? options : [current, ...options];
    const select = el("select", {
      id: idFor(path), "aria-describedby": idFor(path) + "-err",
      onchange: (e) => {
        setAt(draft, path, e.target.value);
        clearError(path);
        updateDirty();
        if (rerender) render();
      },
    }, values.map((v) => el("option", { value: v, selected: v === current }, v)));
    const row = el("div", { class: "row" }, select,
      preview && el("button", { type: "button", "aria-label": `Preview ${current}`, title: "Preview this sound",
        onclick: () => api.preview(select.value) }, "▶"));
    return el("div", { class: "field" }, el("label", { for: idFor(path) }, label), row, errorSlot(path));
  }

  // ---- sections -------------------------------------------------------

  function render() {
    const soundIds = Object.keys(draft.sounds || {});
    statusEl = el("span", { class: "status", role: "status" });
    summaryEl = el("div", { class: "error-summary", role: "alert", hidden: true });
    saveBtn = el("button", { type: "submit", class: "primary", disabled: true }, "Save to YAML");
    const revert = el("button", { type: "button", onclick: load }, "Revert");

    const global = el("fieldset", {}, el("legend", {}, "Global"),
      el("div", { class: "fields" },
        numberField("Master volume", "master_volume", { step: 0.01, min: 0, max: 1 }),
        numberField("Polyphony", "polyphony", { step: 1, min: 1 }),
        numberField("Max events/s", "max_events_per_s", { min: 0 }),
        textField("Scale", "pitched.scale"),
        textField("Root note", "pitched.root"),
        numberField("Octaves", "pitched.range_octaves", { step: 1, min: 1, max: 4 })));

    const signals = Object.entries(draft.signals || {}).map(([name, signal]) => {
      const base = `signals.${name}`;
      const parts = [el("legend", {}, name), errorSlot(base)];
      if (signal.ambient) {
        const a = `${base}.ambient`;
        parts.push(el("div", { class: "fields" },
          selectField("Ambient bed", `${a}.sound`, soundIds, { preview: true }),
          signal.ambient.gain && [
            numberField("From value", `${a}.gain.min_value`),
            numberField("To value", `${a}.gain.max_value`),
            numberField("Gain at start", `${a}.gain.min`, { step: 0.05, min: 0, max: 1 }),
            numberField("Gain at end", `${a}.gain.max`, { step: 0.05, min: 0, max: 1 }),
          ]));
      }
      (signal.events || []).forEach((rule, i) => {
        const r = `${base}.events.${i}`;
        const fields = [
          selectField("Sound", `${r}.sound`, soundIds, { preview: true }),
          selectField("Mode", `${r}.mode`, ["threshold", "pitch_tempo"], { rerender: true }),
          numberField("Above", `${r}.when.above`),
          numberField("Below", `${r}.when.below`),
          numberField("Hysteresis", `${r}.when.hysteresis`, { min: 0 }),
          numberField("Cooldown (s)", `${r}.cooldown_s`, { min: 0 }),
          numberField("Volume", `${r}.volume`, { step: 0.05, min: 0, max: 1 }),
        ];
        if ((rule.mode || "threshold") === "pitch_tempo") {
          fields.push(
            numberField("Pitch from", `${r}.pitch.from`), numberField("Pitch to", `${r}.pitch.to`),
            numberField("Interval at from (s)", `${r}.interval_s.from`, { min: 0 }),
            numberField("Interval at to (s)", `${r}.interval_s.to`, { min: 0 }));
        }
        parts.push(el("fieldset", { class: "rule" }, el("legend", {}, `Rule ${i + 1}`), errorSlot(r), el("div", { class: "fields" }, fields)));
      });
      return el("fieldset", {}, parts);
    });

    form.replaceChildren(summaryEl, global, ...signals,
      el("div", { class: "form-actions" }, saveBtn, revert, statusEl));
    form.onsubmit = save;
    updateDirty();
  }

  // ---- saving + inline validation errors ------------------------------

  function showErrors(errors) {
    const orphans = [];
    for (const { path, message } of errors) {
      // Find the closest field at or above the error's path.
      let keys = split(path);
      let slot = null;
      while (keys.length && !slot) {
        slot = form.querySelector(`[data-err="${keys.join(".")}"]`);
        keys = keys.slice(0, -1);
      }
      if (slot) {
        slot.textContent = message;
        slot.hidden = false;
        const input = form.querySelector(`#${idFor(slot.dataset.err)}`);
        if (input) input.setAttribute("aria-invalid", "true");
      } else {
        orphans.push(`${path || "config"}: ${message}`);
      }
    }
    if (orphans.length) {
      summaryEl.replaceChildren(el("strong", {}, "Other problems"), el("ul", {}, orphans.map((o) => el("li", {}, o))));
      summaryEl.hidden = false;
    }
    const first = form.querySelector("[aria-invalid='true']");
    if (first) first.focus();
  }

  async function save(event) {
    event.preventDefault();
    form.querySelectorAll(".err").forEach((n) => { n.hidden = true; });
    form.querySelectorAll("[aria-invalid]").forEach((n) => n.removeAttribute("aria-invalid"));
    summaryEl.hidden = true;
    const { ok, status, data } = await api.putConfig(draft);
    if (ok) {
      baseline = clone(draft);
      statusEl.className = "status ok";
      statusEl.textContent = `Saved (revision ${data.revision})`;
      if (data.warnings?.length) statusEl.append(el("p", { class: "warnings" }, data.warnings.join(" ")));
      saveBtn.disabled = true;
    } else if (status === 422 && data?.errors) {
      statusEl.className = "status bad";
      statusEl.textContent = `${data.errors.length} problem(s), nothing was saved`;
      showErrors(data.errors);
    } else {
      statusEl.className = "status bad";
      statusEl.textContent = `Save failed (HTTP ${status})`;
    }
  }

  return {
    load,
    // Reload when the daemon's config changed, unless the user has edits.
    configChanged() { if (!baseline || !dirty()) load(); },
  };
}
