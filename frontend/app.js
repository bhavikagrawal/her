/*
  WebSocket driver for HER: chat bubbles, first-run onboarding overlay, waveform during TTS.
  Python owns capture + synthesis; we map JSON events to DOM (including sequential onboarding steps).
  Each `assistant_reset` starts a fresh HER bubble so streamed tokens never collide across turns.
  Plain JS keeps installs dependency-free until you opt into a bundler later.
*/

(() => {
  const WS_URL = "ws://127.0.0.1:8765";
  const CHAT_STREAM = document.getElementById("chat-stream");
  const WF = document.getElementById("waveform");
  const dot = document.getElementById("status-dot");
  const label = document.getElementById("status-label");
  const audioControls = document.getElementById("audio-controls");
  const audioInput = document.getElementById("audio-input");
  const audioOutput = document.getElementById("audio-output");
  const micMeter = document.getElementById("mic-meter");
  const micMeterBar = document.getElementById("mic-meter-bar");
  const micMuteButton = document.getElementById("mic-mute-button");
  const volumeButton = document.getElementById("volume-button");
  const settingsButton = document.getElementById("settings-button");
  const chatButton = document.getElementById("chat-button");
  const chatBar = document.getElementById("chat-bar");
  const chatInput = document.getElementById("chat-input");
  const chatSend = document.getElementById("chat-send");
  const chatClose = document.getElementById("chat-close");
  const onboardingOverlay = document.getElementById("onboarding-overlay");
  const onboardingLabel = document.getElementById("onboarding-label");
  const onboardingInputWrap = document.getElementById("onboarding-input-wrap");
  const onboardingInput = document.getElementById("onboarding-input");
  const onboardingButtons = document.getElementById("onboarding-buttons");
  // Settings live in a separate window (`settings.html`).

  /**
   * HER defaults to English for voice + prompts; onboarding does not ask (other languages still mirror per turn).
   * @type {Array<{ field: string, kind: 'text'|'choice', label: string, options?: Array<{ value: string, label: string }> }>}
   */
  const ONBOARDING_STEPS = [
    { field: "name", kind: "text", label: "What should I call you?" },
    {
      field: "gender",
      kind: "choice",
      label: "How should I refer to you?",
      options: [
        { value: "Male", label: "Male" },
        { value: "Female", label: "Female" },
        { value: "Non-binary", label: "Non-binary" },
        { value: "Prefer not to say", label: "Prefer not to say" },
      ],
    },
    { field: "city", kind: "text", label: "Which city are you in?" },
  ];

  let onboardingStep = 0;
  /** @type {Record<string, string>} */
  let onboardingValues = {};
  let onboardingAwaitReveal = false;

  function clearOnboardingButtons() {
    if (!onboardingButtons) return;
    onboardingButtons.innerHTML = "";
    onboardingButtons.hidden = true;
  }

  function advanceOnboarding() {
    onboardingStep += 1;
    if (onboardingStep >= ONBOARDING_STEPS.length) {
      submitOnboarding();
      return;
    }
    showOnboardingStep(onboardingStep);
  }

  function submitOnboarding() {
    if (!liveSocket || liveSocket.readyState !== WebSocket.OPEN) return;
    liveSocket.send(
      JSON.stringify({
        type: "onboarding_complete",
        values: {
          name: onboardingValues.name,
          gender: onboardingValues.gender,
          city: onboardingValues.city,
        },
      }),
    );
    onboardingAwaitReveal = true;
    fadeOverlayToBlack();
  }

  function renderChoiceButtons(step) {
    if (!onboardingButtons || !step.options) return;
    onboardingButtons.hidden = false;
    onboardingButtons.innerHTML = "";
    for (const opt of step.options) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "onboarding-choice-btn";
      btn.textContent = opt.label;
      btn.addEventListener("click", () => {
        if (step.field === "gender") {
          onboardingValues.gender = opt.value;
          advanceOnboarding();
        }
      });
      onboardingButtons.appendChild(btn);
    }
  }

  function showOnboardingStep(index) {
    if (!onboardingLabel || !onboardingInput || !onboardingOverlay) return;
    const step = ONBOARDING_STEPS[index];
    if (!step) return;
    onboardingOverlay.classList.remove("is-step-visible");
    clearOnboardingButtons();
    window.requestAnimationFrame(() => {
      onboardingLabel.textContent = step.label;
      if (step.kind === "text") {
        if (onboardingInputWrap) onboardingInputWrap.hidden = false;
        onboardingInput.placeholder = "";
        onboardingInput.value = onboardingValues[step.field] || "";
        onboardingOverlay.classList.add("is-step-visible");
        onboardingInput.focus();
      } else if (step.kind === "choice") {
        if (onboardingInputWrap) onboardingInputWrap.hidden = true;
        renderChoiceButtons(step);
        onboardingOverlay.classList.add("is-step-visible");
      }
    });
  }

  function openOnboarding() {
    if (!onboardingOverlay) return;
    onboardingOverlay.classList.remove("is-black", "is-reveal");
    onboardingOverlay.hidden = false;
    onboardingOverlay.setAttribute("aria-hidden", "false");
    onboardingOverlay.classList.add("is-active");
    onboardingStep = 0;
    onboardingValues = {};
    showOnboardingStep(0);
  }

  function fadeOverlayToBlack() {
    if (!onboardingOverlay) return;
    onboardingOverlay.classList.remove("is-step-visible");
    onboardingOverlay.classList.add("is-black");
  }

  function revealOverlayAfterSpeaking() {
    if (!onboardingOverlay) return;
    onboardingOverlay.classList.remove("is-black", "is-active");
    onboardingOverlay.classList.add("is-reveal");
    window.setTimeout(() => {
      onboardingOverlay.hidden = true;
      onboardingOverlay.setAttribute("aria-hidden", "true");
      onboardingOverlay.classList.remove("is-reveal");
    }, 1250);
  }

  function bindOnboardingKeys() {
    if (!onboardingInput) return;
    onboardingInput.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      if (!liveSocket || liveSocket.readyState !== WebSocket.OPEN) return;
      const step = ONBOARDING_STEPS[onboardingStep];
      if (!step) return;

      if (step.kind !== "text") return;

      const val = String(onboardingInput.value || "").trim();
      if (!val) return;
      onboardingValues[step.field] = val;
      advanceOnboarding();
    });
  }

  const MIC_ON_SVG = `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        d="M12 2a3 3 0 0 1 3 3v6a3 3 0 1 1-6 0V5a3 3 0 0 1 3-3Z"
        fill="currentColor"
        opacity="0.9"
      />
      <path
        d="M7 11a1 1 0 0 1 2 0 3 3 0 1 0 6 0 1 1 0 1 1 2 0 5 5 0 0 1-4 4.9V20a1 1 0 1 1-2 0v-3.1A5 5 0 0 1 7 11Z"
        fill="currentColor"
        opacity="0.9"
      />
    </svg>
  `;

  const MIC_OFF_SVG = `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        d="M12 2a3 3 0 0 1 3 3v5.2a1 1 0 0 1-2 0V5a1 1 0 0 0-2 0v1.4a1 1 0 1 1-2 0V5a3 3 0 0 1 3-3Z"
        fill="currentColor"
        opacity="0.9"
      />
      <path
        d="M7 10.2a1 1 0 0 1 2 0V11a3 3 0 0 0 5.2 2 1 1 0 1 1 1.5 1.3A5 5 0 0 1 8 11v-.8Z"
        fill="currentColor"
        opacity="0.9"
      />
      <path
        d="M4 4a1 1 0 0 1 1.4 0l15.6 15.6a1 1 0 1 1-1.4 1.4l-3-3V20a1 1 0 1 1-2 0v-1.4a7 7 0 0 1-4.2 0V20a1 1 0 1 1-2 0v-1.9a7 7 0 0 1-3.4-6.1v-1a1 1 0 1 1 2 0v1c0 1.4.6 2.7 1.6 3.6l-4-4A1 1 0 0 1 4 4Z"
        fill="currentColor"
      />
    </svg>
  `;

  const SPEAKER_ON_SVG = `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        d="M11 4.5a1 1 0 0 1 1.64-.77l4.2 3.5a1 1 0 0 1 .36.77v8a1 1 0 0 1-.36.77l-4.2 3.5A1 1 0 0 1 11 19.5V4.5Z"
        fill="currentColor"
        opacity="0.9"
      />
      <path
        d="M3.5 10a1 1 0 0 1 1-1H11v6H4.5a1 1 0 0 1-1-1v-4Z"
        fill="currentColor"
        opacity="0.9"
      />
      <path
        d="M17.2 8.2a1 1 0 0 1 1.4.1 6 6 0 0 1 0 7.4 1 1 0 0 1-1.6-1.2 4 4 0 0 0 0-5 1 1 0 0 1 .2-1.3Z"
        fill="currentColor"
        opacity="0.75"
      />
      <path
        d="M19.4 6.1a1 1 0 0 1 1.4.2 9 9 0 0 1 0 11.4 1 1 0 1 1-1.6-1.2 7 7 0 0 0 0-9 1 1 0 0 1 .2-1.4Z"
        fill="currentColor"
        opacity="0.45"
      />
    </svg>
  `;

  const SPEAKER_OFF_SVG = `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        d="M11 4.5a1 1 0 0 1 1.64-.77l4.2 3.5a1 1 0 0 1 .36.77v8a1 1 0 0 1-.36.77l-4.2 3.5A1 1 0 0 1 11 19.5V4.5Z"
        fill="currentColor"
        opacity="0.9"
      />
      <path
        d="M3.5 10a1 1 0 0 1 1-1H11v6H4.5a1 1 0 0 1-1-1v-4Z"
        fill="currentColor"
        opacity="0.9"
      />
      <path
        d="M17.4 9.0a1 1 0 0 1 1.42 0l1.2 1.2 1.2-1.2A1 1 0 1 1 22.64 10.4l-1.2 1.2 1.2 1.2a1 1 0 1 1-1.42 1.42l-1.2-1.2-1.2 1.2a1 1 0 1 1-1.42-1.42l1.2-1.2-1.2-1.2a1 1 0 0 1 0-1.42Z"
        fill="currentColor"
      />
    </svg>
  `;

  function tryInvoke(command, args) {
    try {
      // Preferred: global API (requires `app.withGlobalTauri: true`).
      const t = window.__TAURI__;
      const inv =
        (t && t.core && t.core.invoke) ||
        (t && t.tauri && t.tauri.invoke) ||
        (t && t.invoke);
      if (typeof inv !== "function") return null;
      return inv(command, args || {});
    } catch {
      // Fallback: internal invoke (present even without withGlobalTauri).
      try {
        const internal = window.__TAURI_INTERNALS__ && window.__TAURI_INTERNALS__.invoke;
        if (typeof internal === "function") return internal(command, args || {});
      } catch {
        // ignore
      }
      return null;
    }
  }

  /** @type {HTMLDivElement | null} */
  let currentHerBubble = null;
  /** @type {WebSocket | null} */
  let liveSocket = null;
  let isHerSpeaking = false;
  let micMeterEnabled = true;

  // Typewriter rendering for assistant text (keeps "stream" feel even when backend sends sentence chunks).
  let typewriterQueue = "";
  let typewriterRunning = false;

  function pumpTypewriter() {
    if (typewriterRunning) return;
    typewriterRunning = true;
    const step = () => {
      if (!typewriterQueue) {
        typewriterRunning = false;
        return;
      }
      const ch = typewriterQueue[0];
      typewriterQueue = typewriterQueue.slice(1);
      if (!currentHerBubble) resetAssistantBubble();
      if (currentHerBubble) currentHerBubble.textContent += ch;
      CHAT_STREAM?.scrollTo({ top: CHAT_STREAM.scrollHeight, behavior: "smooth" });
      window.setTimeout(step, 14);
    };
    step();
  }

  /**
   * @param {HTMLElement | null} el
   * @returns {HTMLSelectElement | null}
   */
  function asSelect(el) {
    return el && el.tagName === "SELECT" ? /** @type {HTMLSelectElement} */ (el) : null;
  }

  const inputSelect = asSelect(audioInput);
  const outputSelect = asSelect(audioOutput);
  const LS_IN = "her.audio.input_id";
  const LS_OUT = "her.audio.output_id";
  const LS_SETTINGS = "her.settings.v1";

  /** @type {Record<string, any>} */
  let settingsValues = {};
  /** @type {Array<any>} */
  let settingsSchema = [];
  let settingsInitialized = false;
  let ttsMuted = false;
  let micMuted = false;

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
    if (!liveSocket || liveSocket.readyState !== WebSocket.OPEN) return;
    liveSocket.send(JSON.stringify({ type: "set_settings", values }));
  }

  function setVolumeUi(muted) {
    ttsMuted = Boolean(muted);
    if (volumeButton) volumeButton.classList.toggle("is-active", ttsMuted);
    if (volumeButton) {
      volumeButton.innerHTML = ttsMuted ? SPEAKER_OFF_SVG : SPEAKER_ON_SVG;
      volumeButton.setAttribute("aria-label", ttsMuted ? "Unmute HER voice" : "Mute HER voice");
      volumeButton.setAttribute("title", ttsMuted ? "Unmute HER voice" : "Mute HER voice");
    }
  }

  function setMicMuteUi(muted) {
    micMuted = Boolean(muted);
    if (micMuteButton) micMuteButton.classList.toggle("is-active", micMuted);
    if (micMuteButton) {
      micMuteButton.innerHTML = micMuted ? MIC_OFF_SVG : MIC_ON_SVG;
      micMuteButton.setAttribute("aria-label", micMuted ? "Unmute microphone" : "Mute microphone");
      micMuteButton.setAttribute("title", micMuted ? "Unmute microphone" : "Mute microphone");
    }
  }

  // Schema is still received so we can apply saved overrides once.

  /**
   * @param {Array<{id:number,name:string,default?:boolean}>} devices
   * @param {HTMLSelectElement | null} select
   */
  function fillDeviceSelect(devices, select) {
    if (!select) return;
    select.innerHTML = "";
    for (const dev of devices) {
      const opt = document.createElement("option");
      opt.value = String(dev.id);
      opt.textContent = dev.name || `Device ${dev.id}`;
      if (dev.default) opt.selected = true;
      select.appendChild(opt);
    }
  }

  /**
   * Restore last chosen device id if it still exists in `devices`.
   * @param {Array<{id:number}>} devices
   * @param {HTMLSelectElement | null} select
   * @param {string} storageKey
   * @returns {boolean} true when a stored selection was applied
   */
  function restoreSelection(devices, select, storageKey) {
    if (!select) return false;
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return false;
    const wanted = Number(raw);
    if (!Number.isFinite(wanted)) return false;
    const exists = devices.some((d) => d && typeof d.id === "number" && d.id === wanted);
    if (!exists) return false;
    select.value = String(wanted);
    return true;
  }

  /**
   * Persist current selection (or clear when invalid).
   * @param {HTMLSelectElement | null} select
   * @param {string} storageKey
   */
  function persistSelection(select, storageKey) {
    if (!select) return;
    const val = Number(select.value);
    if (!Number.isFinite(val)) {
      window.localStorage.removeItem(storageKey);
      return;
    }
    window.localStorage.setItem(storageKey, String(val));
  }

  function maybeShowAudioControls(inputs, outputs) {
    if (!audioControls) return;
    const nIn = inputs && inputs.length ? inputs.length : 0;
    const nOut = outputs && outputs.length ? outputs.length : 0;
    const show = nIn >= 1 || nOut >= 1;
    audioControls.classList.toggle("audio-controls--hidden", !show);
  }

  function sendAudioSelection() {
    if (!liveSocket || liveSocket.readyState !== WebSocket.OPEN) return;
    const inId = inputSelect ? Number(inputSelect.value) : null;
    const outId = outputSelect ? Number(outputSelect.value) : null;
    liveSocket.send(
      JSON.stringify({
        type: "set_audio_devices",
        input_id: Number.isFinite(inId) ? inId : null,
        output_id: Number.isFinite(outId) ? outId : null,
      }),
    );
  }

  /**
   * Connection badge (“connected” + green LED).
   * @param {boolean} ok
   * @param {string} text
   */
  function setStatus(ok, text) {
    if (!dot || !label) return;
    dot.classList.toggle("is-connected", ok);
    label.textContent = text;
  }

  function setMicMeterActive(active) {
    if (!micMeter) return;
    micMeter.classList.toggle("mic-meter--hidden", !active);
  }

  /**
   * Map dBFS-ish level to 0..1 UI fill.
   * @param {number} db
   * @returns {number}
   */
  function meterFillFromDb(db) {
    // -60 dB => 0%, -12 dB => ~100%
    const clamped = Math.max(-60, Math.min(-12, db));
    return (clamped + 60) / 48;
  }

  /**
   * @param {number} db
   */
  function setMicMeterDb(db) {
    if (!micMeterBar) return;
    const fill = meterFillFromDb(db);
    micMeterBar.style.width = `${Math.round(fill * 100)}%`;
  }

  /**
   * Append a div.bubble with role-specific styling.
   * @param {"user"|"her"} who
   * @param {string} text
   * @returns {HTMLDivElement}
   */
  function appendBubble(who, text) {
    const row = document.createElement("div");
    row.className = `bubble-row bubble-row--${who}`;
    const bubble = document.createElement("div");
    bubble.className = `bubble bubble--${who}`;
    bubble.textContent = text;
    row.appendChild(bubble);
    if (CHAT_STREAM) CHAT_STREAM.appendChild(row);
    CHAT_STREAM?.scrollTo({ top: CHAT_STREAM.scrollHeight, behavior: "smooth" });
    return bubble;
  }

  function resetAssistantBubble() {
    currentHerBubble = appendBubble("her", "");
    return currentHerBubble;
  }

  /**
   * Build decorative waveform bars (shown only while backend sets `her_speaking`).
   */
  function ensureWaveformBars() {
    if (!WF) return;
    WF.innerHTML = "";
    const count = 32;
    for (let i = 0; i < count; i += 1) {
      const bar = document.createElement("span");
      bar.className = "waveform__bar";
      bar.style.setProperty("--bar-index", String(i));
      WF.appendChild(bar);
    }
  }

  /**
   * @param {boolean} active
   */
  function setHerSpeaking(active) {
    if (!WF) return;
    WF.classList.toggle("is-active", active);
    if (active && WF.childElementCount === 0) {
      ensureWaveformBars();
    }
  }

  function connect() {
    setStatus(false, "connecting…");
    let socket;
    try {
      socket = new WebSocket(WS_URL);
      liveSocket = socket;
    } catch (err) {
      console.error(err);
      setStatus(false, "could not start client");
      return;
    }

    socket.addEventListener("open", () => {
      setStatus(false, "negotiating…");
      try {
        socket.send(JSON.stringify({ type: "client_role", role: "voice" }));
      } catch {
        // ignore
      }
      if (inputSelect) {
        inputSelect.addEventListener("change", () => {
          persistSelection(inputSelect, LS_IN);
          sendAudioSelection();
        });
      }
      if (outputSelect) {
        outputSelect.addEventListener("change", () => {
          persistSelection(outputSelect, LS_OUT);
          sendAudioSelection();
        });
      }
      if (settingsButton) {
        settingsButton.addEventListener("click", () => {
          const p = tryInvoke("open_settings_window");
          if (p && typeof p.then === "function") {
            p.catch((err) => console.error(err));
            return;
          }
          appendBubble("her", "⚠ Settings window is only available in the desktop app (Tauri).");
        });
      }
      if (chatButton) {
        chatButton.addEventListener("click", () => {
          const nextHidden = chatBar ? chatBar.classList.toggle("chat-bar--hidden") : true;
          chatButton.classList.toggle("is-active", !nextHidden);
          document.body.classList.toggle("chat-open", !nextHidden);
          if (!nextHidden && chatInput && typeof chatInput.focus === "function") {
            chatInput.focus();
          }
        });
      }
      if (chatClose) {
        chatClose.addEventListener("click", () => {
          if (chatBar) chatBar.classList.add("chat-bar--hidden");
          if (chatButton) chatButton.classList.remove("is-active");
          document.body.classList.remove("chat-open");
        });
      }

      function sendTypedMessage() {
        if (!liveSocket || liveSocket.readyState !== WebSocket.OPEN) return;
        if (!chatInput) return;
        const text = String(chatInput.value || "").trim();
        if (!text) return;
        liveSocket.send(JSON.stringify({ type: "user_text", text }));
        chatInput.value = "";
      }

      if (chatSend) {
        chatSend.addEventListener("click", sendTypedMessage);
      }
      if (chatInput) {
        chatInput.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            sendTypedMessage();
          }
          if (e.key === "Escape") {
            if (chatBar) chatBar.classList.add("chat-bar--hidden");
            if (chatButton) chatButton.classList.remove("is-active");
            document.body.classList.remove("chat-open");
          }
        });
      }

      if (volumeButton) {
        volumeButton.addEventListener("click", () => {
          const next = !ttsMuted;
          setVolumeUi(next);
          const merged = { ...(settingsValues || {}), tts_muted: next };
          settingsValues = merged;
          saveSettings(settingsValues);
          sendSettings({ tts_muted: next });
        });
      }

      if (micMuteButton) {
        micMuteButton.addEventListener("click", () => {
          const next = !micMuted;
          setMicMuteUi(next);
          sendSettings({ mic_muted: next });
        });
      }
    });

    socket.addEventListener("message", (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "status" && payload.connected) {
          setStatus(true, "connected");
          return;
        }
        if (payload.type === "onboarding_status") {
          if (payload.first_launch) {
            openOnboarding();
          }
          return;
        }
        if (payload.type === "voice_ready") {
          setStatus(true, "listening…");
          setMicMeterActive(true);
          return;
        }
        if (payload.type === "status_text" && payload.text) {
          setStatus(true, String(payload.text));
          return;
        }
        if (payload.type === "user_transcript" && payload.text) {
          appendBubble("user", payload.text);
          return;
        }
        if (payload.type === "assistant_reset") {
          resetAssistantBubble();
          typewriterQueue = "";
          return;
        }
        if (payload.type === "assistant_delta" && payload.text) {
          typewriterQueue += String(payload.text);
          pumpTypewriter();
          return;
        }
        if (payload.type === "her_speaking") {
          isHerSpeaking = Boolean(payload.active);
          setHerSpeaking(isHerSpeaking);
          if (payload.active && onboardingAwaitReveal) {
            onboardingAwaitReveal = false;
            revealOverlayAfterSpeaking();
          }
          // Hide mic meter while speaking to reduce “why is it moving?” confusion.
          setMicMeterActive(micMeterEnabled && !isHerSpeaking);
          return;
        }
        if (payload.type === "mic_level") {
          if (micMeterEnabled && typeof payload.db === "number") setMicMeterDb(payload.db);
          return;
        }
        if (payload.type === "settings_schema") {
          settingsSchema = Array.isArray(payload.schema) ? payload.schema : [];
          const serverValues = payload.values && typeof payload.values === "object" ? payload.values : {};
          if (!settingsInitialized) {
            const saved = loadSavedSettings();
            settingsValues = { ...serverValues, ...saved };
            saveSettings(settingsValues);
            micMeterEnabled = Boolean(settingsValues.mic_meter ?? true);
            setVolumeUi(Boolean(settingsValues.tts_muted ?? false));
            setMicMeterActive(micMeterEnabled && !isHerSpeaking);
            // Apply saved overrides once (avoid fighting user changes).
            sendSettings(saved);
            settingsInitialized = true;
          } else {
            // Refresh values from backend without re-applying localStorage every time.
            settingsValues = { ...settingsValues, ...serverValues };
            micMeterEnabled = Boolean(settingsValues.mic_meter ?? true);
            setVolumeUi(Boolean(settingsValues.tts_muted ?? ttsMuted));
            setMicMeterActive(micMeterEnabled && !isHerSpeaking);
          }
          return;
        }
        if (payload.type === "audio_devices") {
          const inputs = Array.isArray(payload.inputs) ? payload.inputs : [];
          const outputs = Array.isArray(payload.outputs) ? payload.outputs : [];
          fillDeviceSelect(inputs, inputSelect);
          fillDeviceSelect(outputs, outputSelect);
          const restoredIn = restoreSelection(inputs, inputSelect, LS_IN);
          const restoredOut = restoreSelection(outputs, outputSelect, LS_OUT);
          maybeShowAudioControls(inputs, outputs);
          // CONCEPT: Only re-send to backend when our restored choice actually differs
          // from what backend currently has. Otherwise we create a restart feedback loop
          // (backend re-emits audio_devices → we re-send → backend restarts mic → …).
          if (restoredIn || restoredOut) {
            const wantIn = inputSelect ? Number(inputSelect.value) : null;
            const wantOut = outputSelect ? Number(outputSelect.value) : null;
            const haveIn = typeof payload.selected_input === "number" ? payload.selected_input : null;
            const haveOut = typeof payload.selected_output === "number" ? payload.selected_output : null;
            const inDiffers = (Number.isFinite(wantIn) ? wantIn : null) !== haveIn;
            const outDiffers = (Number.isFinite(wantOut) ? wantOut : null) !== haveOut;
            if (inDiffers || outDiffers) {
              sendAudioSelection();
            }
          }
          return;
        }
        if (payload.type === "error") {
          const detail = payload.message || "unknown error";
          appendBubble("her", `⚠ ${detail}`);
          return;
        }
      } catch (err) {
        console.error(err);
      }
    });

    socket.addEventListener("close", () => {
      setStatus(false, "disconnected");
      setHerSpeaking(false);
      setMicMeterActive(false);
      liveSocket = null;
    });

    socket.addEventListener("error", () => {
      setStatus(false, "connection error");
    });
  }

  ensureWaveformBars();
  window.addEventListener("DOMContentLoaded", () => {
    bindOnboardingKeys();
    connect();
  });
})();
