// Thin fetch wrappers. Everything is same-origin; nothing leaves localhost.

async function request(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  try { data = await response.json(); } catch { /* empty body */ }
  return { ok: response.ok, status: response.status, data };
}

export const api = {
  getConfig: () => request("GET", "/config"),
  putConfig: (config) => request("PUT", "/config", config),
  preview: (sound, pitch) => request("POST", `/preview/${encodeURIComponent(sound)}`, pitch == null ? undefined : { pitch }),
  setMuted: (muted) => request("POST", "/mute", { muted }),
  setVolume: (volume) => request("PUT", "/volume", { volume }),
  setMixer: (sound, patch) => request("PUT", `/mixer/${encodeURIComponent(sound)}`, patch),
  setSolo: (sound) => request("PUT", "/solo", { sound }),
};

export function debounce(fn, ms = 150) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === false || value == null) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}
