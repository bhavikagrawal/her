/*
  Settings window controller (separate Tauri window).
  CONCEPT: We reuse the backend-provided settings schema, persist to localStorage,
  and send live updates over the same WebSocket as the main window.
*/

(() => {
  const WS_URL = "ws://127.0.0.1:8765";
  const settingsBody = document.getElementById("settings-body");
  const LS_SETTINGS = "her.settings.v1";

  /** @type {WebSocket | null} */
  let socket = null;
  /** @type {Record<string, any>} */
  let settingsValues = {};
  /** @type {Array<any>} */
  let settingsSchema = [];
  let settingsInitialized = false;

  function loadSavedSettings() {
    try {
      const raw = window.localStorage.getItem(LS_SETTINGS);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }

  function saveSettings(values) {
    try {
      window.localStorage.setItem(LS_SETTINGS, JSON.stringify(values));
    } catch {
      // ignore
    }
  }

  function sendSettings(values) {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: "set_settings", values }));
  }

  function renderSettings() {
    if (!settingsBody) return;
    settingsBody.innerHTML = "";
    for (const field of settingsSchema) {
      const key = field.key;
      const row = document.createElement("div");
      row.className = "setting-row";

      const labelWrap = document.createElement("div");
      labelWrap.className = "setting-row__label";
      const label = document.createElement("span");
      label.textContent = field.label || key;
      const info = document.createElement("span");
      info.className = "setting-row__info";
      info.textContent = "i";
      info.tabIndex = 0;
      const tip = document.createElement("span");
      tip.className = "setting-row__tooltip";
      tip.textContent = field.help || "";
      labelWrap.appendChild(label);
      labelWrap.appendChild(info);
      labelWrap.appendChild(tip);

      const controlWrap = document.createElement("div");
      const valueWrap = document.createElement("div");
      valueWrap.className = "setting-row__value";

      const current = settingsValues[key];

      if (field.kind === "toggle") {
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = Boolean(current);
        input.addEventListener("change", () => {
          settingsValues[key] = Boolean(input.checked);
          saveSettings(settingsValues);
          sendSettings({ [key]: settingsValues[key] });
          valueWrap.textContent = input.checked ? "On" : "Off";
        });
        controlWrap.appendChild(input);
        valueWrap.textContent = input.checked ? "On" : "Off";
      } else {
        const rangeWrap = document.createElement("div");
        rangeWrap.className = "setting-row__range";
        const input = document.createElement("input");
        input.type = "range";
        input.min = String(field.min);
        input.max = String(field.max);
        input.step = String(field.step);
        input.value = String(current ?? field.min);
        const minLabel = document.createElement("span");
        minLabel.className = "setting-row__range-bound";
        minLabel.textContent = String(field.min);
        const maxLabel = document.createElement("span");
        maxLabel.className = "setting-row__range-bound";
        maxLabel.textContent = String(field.max);
        const fmt = (v) => {
          if (Number.isInteger(field.step)) return String(Math.round(v));
          return String(Math.round(v * 100) / 100);
        };
        valueWrap.textContent = fmt(Number(input.value));
        input.addEventListener("input", () => {
          const v = Number(input.value);
          settingsValues[key] = Number.isFinite(v) ? v : settingsValues[key];
          valueWrap.textContent = fmt(v);
        });
        input.addEventListener("change", () => {
          saveSettings(settingsValues);
          sendSettings({ [key]: settingsValues[key] });
        });
        rangeWrap.appendChild(minLabel);
        rangeWrap.appendChild(input);
        rangeWrap.appendChild(maxLabel);
        controlWrap.appendChild(rangeWrap);
      }

      row.appendChild(labelWrap);
      row.appendChild(controlWrap);
      row.appendChild(valueWrap);
      settingsBody.appendChild(row);
    }
  }

  function connect() {
    socket = new WebSocket(WS_URL);
    socket.addEventListener("open", () => {
      try {
        socket.send(JSON.stringify({ type: "client_role", role: "settings" }));
      } catch {
        // ignore
      }
    });
    socket.addEventListener("message", (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "settings_schema") {
          settingsSchema = Array.isArray(payload.schema) ? payload.schema : [];
          const serverValues = payload.values && typeof payload.values === "object" ? payload.values : {};
          const saved = loadSavedSettings();
          settingsValues = { ...serverValues, ...saved };
          saveSettings(settingsValues);
          renderSettings();
          // Apply saved values exactly once to avoid an infinite schema↔settings loop.
          if (!settingsInitialized) {
            settingsInitialized = true;
            sendSettings(saved);
          }
        }
      } catch {
        // ignore
      }
    });
  }

  window.addEventListener("DOMContentLoaded", connect);
})();

