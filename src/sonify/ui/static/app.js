import { api, debounce } from "./api.js";
import { createEditor } from "./editor.js";
import { createMixer } from "./mixer.js";
import { createTiles } from "./tiles.js";
import { createTimeline } from "./timeline.js";

const $ = (id) => document.getElementById(id);

const tiles = createTiles($("tiles"));
const mixer = createMixer($("mixer"));
const editor = createEditor($("editor"));
const timeline = createTimeline({
  list: $("timeline"),
  soundFilter: $("f-sound"),
  signalFilter: $("f-signal"),
  suppressedBox: $("f-suppressed"),
});

// ---- header: connection, master volume, mute --------------------------

const conn = $("conn");
function setConnection(state, text) {
  conn.dataset.state = state;
  $("conn-text").textContent = text;
}

const volume = $("master-vol");
const sendVolume = debounce((v) => api.setVolume(v));
volume.addEventListener("input", () => {
  $("master-out").textContent = Math.round(volume.value * 100) + "%";
  sendVolume(Number(volume.value));
});
$("mute-btn").addEventListener("click", () => api.setMuted($("mute-btn").getAttribute("aria-pressed") !== "true"));

function applyState(state) {
  if (document.activeElement !== volume) {
    volume.value = state.volume;
    $("master-out").textContent = Math.round(state.volume * 100) + "%";
  }
  const muteBtn = $("mute-btn");
  muteBtn.setAttribute("aria-pressed", String(state.muted));
  muteBtn.textContent = state.muted ? "Muted" : "Mute";
  mixer.update(state);
}

// ---- screen reader announcements (throttled) --------------------------

let lastAnnounce = 0;
function announce(data) {
  const now = Date.now();
  if (data.suppressed || now - lastAnnounce < 2000) return;
  lastAnnounce = now;
  $("sr-live").textContent = `${data.sound} played for ${data.signal}`;
}

// ---- websocket with automatic reconnect -------------------------------

function handle(message) {
  const { type, data, ts } = message;
  switch (type) {
    case "snapshot":
      tiles.reset(data);
      timeline.reset(data);
      applyState(data.state);
      break;
    case "metric": tiles.metric(data, ts); break;
    case "sound": tiles.sound(data); timeline.add(data, ts); announce(data); break;
    case "state": applyState(data); break;
    case "config": editor.configChanged(); break;
  }
}

let retry = 0;
function connect() {
  setConnection("connecting", retry ? "Reconnecting" : "Connecting");
  const socket = new WebSocket(`ws://${location.host}/ws`);
  socket.addEventListener("open", () => { retry = 0; setConnection("open", "Connected"); editor.configChanged(); });
  socket.addEventListener("message", (e) => handle(JSON.parse(e.data)));
  socket.addEventListener("close", () => {
    setConnection("closed", "Disconnected, retrying");
    const delay = Math.min(10000, 500 * 2 ** retry++);
    setTimeout(connect, delay);
  });
  socket.addEventListener("error", () => socket.close());
}

editor.load();
connect();
