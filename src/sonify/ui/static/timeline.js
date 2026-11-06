import { el } from "./api.js";

const MAX = 200;

export function createTimeline({ list, soundFilter, signalFilter, suppressedBox }) {
  let entries = []; // newest first
  const sounds = new Set();
  const signals = new Set();

  const fmt = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour12: false });

  function syncOptions(select, values) {
    const current = select.value;
    select.replaceChildren(el("option", { value: "" }, "all"), ...[...values].sort().map((v) => el("option", { value: v }, v)));
    select.value = values.has(current) ? current : "";
  }

  function render() {
    const rows = entries.filter(
      (e) =>
        (!soundFilter.value || e.sound === soundFilter.value) &&
        (!signalFilter.value || e.signal === signalFilter.value) &&
        (suppressedBox.checked || !e.suppressed),
    );
    if (!rows.length) {
      list.replaceChildren(el("li", { class: "empty" }, "No sound events yet."));
      return;
    }
    list.replaceChildren(
      ...rows.map((e) =>
        el(
          "li",
          { class: e.suppressed ? "suppressed" : "" },
          el("span", { class: "time" }, fmt(e.ts)),
          el("span", {}, el("span", { class: "snd" }, e.sound), ` ← ${e.signal} ${Number(e.trigger_value).toFixed(1)}`),
          e.suppressed ? el("span", { class: "sup" }, e.suppressed) : "",
        ),
      ),
    );
  }

  function track(e) {
    if (!sounds.has(e.sound)) { sounds.add(e.sound); syncOptions(soundFilter, sounds); }
    if (!signals.has(e.signal)) { signals.add(e.signal); syncOptions(signalFilter, signals); }
  }

  for (const control of [soundFilter, signalFilter, suppressedBox]) control.addEventListener("change", render);

  return {
    reset(snapshot) {
      entries = [...snapshot.recent_sounds].reverse().slice(0, MAX);
      entries.forEach(track);
      render();
    },
    add(data, ts) {
      const entry = { ...data, ts };
      entries.unshift(entry);
      entries.length = Math.min(entries.length, MAX);
      track(entry);
      render();
    },
  };
}
