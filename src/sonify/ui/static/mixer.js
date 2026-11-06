import { api, debounce, el } from "./api.js";

export function createMixer(root) {
  const rows = new Map(); // sound -> {row, vol, volOut, cd, cdOut, mute, solo}
  let solo = null;

  function build(perSound) {
    root.replaceChildren();
    rows.clear();
    for (const [sound, info] of Object.entries(perSound)) {
      const volId = `mix-vol-${sound}`;
      const cdId = `mix-cd-${sound}`;
      const volOut = el("output", { for: volId });
      const cdOut = el("output", { for: cdId });
      const sendVol = debounce((v) => api.setMixer(sound, { volume: v }));
      const sendCd = debounce((v) => api.setMixer(sound, { cooldown_s: v }));
      const vol = el("input", { id: volId, type: "range", min: 0, max: 1, step: 0.01, "aria-label": `${sound} volume`,
        oninput: (e) => { volOut.textContent = Math.round(e.target.value * 100) + "%"; sendVol(Number(e.target.value)); } });
      const cd = el("input", { id: cdId, type: "range", min: 0, max: 30, step: 0.05, "aria-label": `${sound} cooldown seconds`,
        oninput: (e) => { cdOut.textContent = Number(e.target.value).toFixed(2) + "s"; sendCd(Number(e.target.value)); } });
      const mute = el("button", { type: "button", "aria-pressed": "false", title: `Mute ${sound}`,
        onclick: () => api.setMixer(sound, { muted: mute.getAttribute("aria-pressed") !== "true" }) }, "M");
      const soloBtn = el("button", { type: "button", "aria-pressed": "false", title: `Solo ${sound}`,
        onclick: () => api.setSolo(solo === sound ? null : sound) }, "S");
      const play = el("button", { type: "button", title: `Preview ${sound}`, "aria-label": `Preview ${sound}`,
        onclick: () => api.preview(sound) }, "▶");
      const row = el("div", { class: "mix-row", role: "group", "aria-label": sound },
        el("span", { class: "name" }, sound),
        el("div", { class: "ctl" }, el("span", {}, "Vol"), vol, volOut),
        el("div", { class: "ctl" }, el("span", {}, "CD"), cd, cdOut),
        el("div", { class: "btns" }, play, mute, soloBtn));
      root.append(row);
      rows.set(sound, { row, vol, volOut, cd, cdOut, mute, solo: soloBtn });
    }
  }

  return {
    update(state) {
      const ids = Object.keys(state.per_sound);
      if (ids.length !== rows.size || ids.some((id) => !rows.has(id))) build(state.per_sound);
      solo = state.solo;
      const playing = new Set(state.active.map((a) => a.sound));
      for (const [sound, info] of Object.entries(state.per_sound)) {
        const r = rows.get(sound);
        if (document.activeElement !== r.vol) { r.vol.value = info.volume; r.volOut.textContent = Math.round(info.volume * 100) + "%"; }
        if (document.activeElement !== r.cd) { r.cd.value = Math.min(info.cooldown_s, 30); r.cdOut.textContent = info.cooldown_s.toFixed(2) + "s"; }
        r.mute.setAttribute("aria-pressed", String(info.muted));
        r.solo.setAttribute("aria-pressed", String(state.solo === sound));
        r.row.classList.toggle("playing", playing.has(sound));
      }
    },
  };
}
