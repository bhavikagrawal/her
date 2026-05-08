# PHASE_COMPLETE — HER

## What Phase 1 delivered

- `backend/voice/session.py` `VoiceSession`: 16 kHz capture, `silero-vad-lite` with barge-in, `whisper.cpp` STT, Ollama `qwen2.5:7b` **streaming** to the UI, **Kokoro** TTS.
- `backend/main.py` spawns one **daemon** voice thread per WebSocket client; JSON event types: `voice_ready`, `user_transcript`, `assistant_reset`, `assistant_delta`, `her_speaking`, `error`.
- `frontend/`: user bubbles (right), HER (left) with live token deltas, bottom **waveform** when `her_speaking` is active.
- `scripts/download_voice_models.sh` for Kokoro weights; optional `scripts/download_whisper_medium.sh` for whisper.cpp medium weights; `setup.sh` now prefers **Python 3.12**, reuses venv, runs Kokoro download, and ensures the Tauri **RGBA** icon exists.
- On-screen name is hardcoded **User** (per Phase 1 spec) for system-prompt testing.

## What Phase 1.5 delivered (multilingual)

- **STT**: `whisper.cpp` runs with `-l auto` by default; `backend/voice/transcriber.py` parses Whisper's `auto-detected language: xx` from stderr and returns a `Transcript(text, language, detected)` to the session.
- **Text routing**: `backend/voice/lang_routing.py` uses [`lingua-language-detector`](https://github.com/pemistahl/lingua-py) (offline, ~170 MB n-gram models) for typed input; sticky to English on short / ambiguous text so utterances like "sure" or "i am good" never flip away from English.
- **TTS**: `backend/voice/synthesizer.py` now picks a Kokoro voice for the detected language (en, es, fr, it, pt, hi, ja, zh) and shells out to macOS `say` for the rest (de, ru, ko, ar, nl, tr, pl, sv). Kokoro failures are blacklisted per voice/lang at runtime, so subsequent turns skip straight to `say`.
- **Prompt mirroring**: the system prompt now contains a per-turn `## Language for this turn` block telling the LLM to mirror the user's language. The "English-only" error gate is removed — language is a routing signal, never a blocker.
- **WebSocket**: `user_transcript` and `her_speaking` events now include a `lang` field for the UI to surface the detected language.

## What Phase 2 delivered

- **[MemPalace](https://github.com/MemPalace/mempalace)** as **local-first** long-term memory: verbatim turn files under `data/mempalace/her_turns/`, Chroma semantic search, wake-up context from `data/mempalace/identity.txt`.
- `backend/memory/mempalace_adapter.py`: ingest after each user+assistant turn; retrieve before each model call; env toggles documented in `ENVIRONMENT.md`.
- `backend/voice/session.py`: injects a bounded **MemPalace** block into the system prompt; records exchanges with a stable per-session key.
- `backend/main.py`: WebSocket `{"type":"memory_status"}` returns JSON status (drawer counts, paths).
- `scripts/her_memory_status.sh`: prints the same status without opening the app (requires venv + `PYTHONPATH`).

## What Phase 3 delivered (onboarding + greeting)

- **`data/profile.json`** — single-user onboarding answers (`name`, `gender`, `city`; **`preferred_language` defaults to English** / `en`), `setup_complete`, plus offline **`location`** `{country, region, confident}` from local **`qwen2.5:7b`** (`backend/onboarding/location.py`).
- **`backend/onboarding/profile.py`** — atomic JSON read/write; **`backend/onboarding/greeting.py`** — first-greeting chat messages; voice pipeline unchanged for streaming + Kokoro/`say`.
- **`backend/main.py`** — after `status connected`, sends **`onboarding_status`** `{first_launch, profile}`; **`onboarding_complete`** from the UI is queued into `VoiceSession`.
- **`backend/voice/session.py`** — defers the normal session opener until onboarding finishes when `first_launch`; **`onboarding_resolved`** echoes resolved location; system prompt gains a **User profile** block for every turn after setup.
- **`frontend/`** — fullscreen overlay: one question at a time, **Enter** advances/submits (no button); fade to black, then overlay fades out when **`her_speaking`** starts so text + waveform appear as HER speaks.

## What Phase 0 delivered (foundation)

- Folder skeleton under `backend/`, `frontend/`, `src-tauri/`, `scripts/`, and `agent_library/`.
- Teaching comment headers on each source file explaining purpose and relationships.
- `src-tauri/`: Tauri v2 shell; `beforeDevCommand` runs `bash scripts/run-backend.sh` from the app root.
- Bundling is disabled (`bundle.active: false`) until a full icon set is needed for release.

---

## PHASE TEST STEPS

PHASE 0 — Skeleton

What to test: Tauri window opens. Python backend starts. Frontend says "connected."

Steps:

```
cd her
bash setup.sh
cd src-tauri && cargo tauri dev
```

What you should see:

Terminal: `Python WebSocket server started on ws://localhost:8765`

App window: dark screen with small "connected" indicator, green dot

Most likely failure:

`Port 8765 already in use` → run: `lsof -i :8765 | grep LISTEN`

Kill the PID shown, then retry.

Pass condition: green dot visible in window, no errors in terminal.

---

PHASE 1 — Voice loop

What to test: full voice conversation works. Interruption works.

Steps:

```
cargo tauri dev   (from src-tauri)
Speak: "Hello, what is your name?"
Wait for response to start, then speak again mid-sentence.
```

What you should see:

Your words appear as a bubble on the right.

HER's response appears on the left, word by word as she speaks.

When you interrupt: HER stops immediately, your new bubble appears.

Most likely failure:

Mic not detected → System Preferences > Privacy > Microphone > allow Terminal

Whisper not found → run: `which whisper-cli` (should show a path)

No sound output → check: `python3 -c "import sounddevice; print(sounddevice.query_devices())"`

Pass condition: full conversation, clean interruption.

---

PHASE 1.5 — Multilingual mirroring

What to test: HER detects the language each turn and replies in it (Kokoro when supported, macOS `say` fallback otherwise). The old "English-only" error must NOT appear.

Steps:

```
cargo tauri dev   (from src-tauri)

# 1. Start in English: "Tell me a fun fact about octopuses."
#    → English transcript, English reply, Kokoro voice.

# 2. Switch to French: "Salut, comment vas-tu aujourd'hui ?"
#    → user_transcript shows lang="fr", HER replies in French (Kokoro `ff_siwis`).

# 3. Try a Kokoro-less language — German: "Erzähl mir einen Witz auf Deutsch."
#    → lang="de", HER speaks via macOS `say -v Anna`.

# 4. Type (don't speak) "i am good" or "sure" in the chat bar.
#    → No "English-only" error. HER replies in English.

# 5. Type a non-Latin sentence: "मैं ठीक हूँ धन्यवाद"
#    → lang="hi", Kokoro Hindi voice (`hf_alpha`).
```

What you should see:

- No `error` event with `stage: "language"` ever.
- `user_transcript` events include a `lang` field.
- Backend logs (with `HER_VOICE_TIMING_LOG=1`): `voice_timing stage=whisper_done … lang=fr` and similar.

Most likely failure:

`say` voice not installed (e.g. on a stripped-down macOS) → HER uses the system default voice automatically; check `say -v ?` for available voices.

Kokoro phonemizer crashes on a language → that voice/lang pair is added to a session-level blacklist and subsequent calls fall through to `say`.

Pass condition: HER mirrors EN, FR, DE, HI in one session without errors.

---

PHASE 2 — Memory (MemPalace)

What to test: HER remembers across sessions using **MemPalace** (local Chroma + turn files).

Steps:

```
cd her
bash setup.sh
cargo tauri dev   (from src-tauri)

# In the app: say "My favourite food is biryani and I hate mornings."
# Have HER reply, then quit the app completely.

# Optional — inspect memory without the UI:
bash scripts/her_memory_status.sh

# Relaunch: cargo tauri dev
# Say: "What do you know about my food preferences?"
```

What you should see:

HER mentions **biryani** (or your wording) without you repeating the fact.

On disk (paths relative to repo; respect `HER_DATA_DIR` if set):

```
ls data/mempalace/her_turns/
ls data/mempalace/chroma* 2>/dev/null || ls data/mempalace/
```

Chroma persists SQLite under the palace directory (layout may include a `chroma/` folder depending on MemPalace/Chroma version).

Most likely failure:

First-time embedding download blocked → ensure `~/.cache/chroma/onnx_models/` is writable (see `ENVIRONMENT.md`).

`HER_MEMPALACE_ENABLED=0` → memory disabled; unset or set to `1`.

Pass condition: biryani recalled correctly after **full app restart**.

**Wipe memory (audit / fresh start):** quit the app, then `rm -rf data/mempalace` (or only `data/mempalace/her_turns` + chroma subfolder if you know the layout). Re-run the scenario.

---

PHASE 3 — Onboarding + greeting

What to test: first-launch form works (city, not full address). Greeting is spoken and feels cinematic.

Steps:

```
cd her
rm -f data/profile.json   (wipe profile to simulate first launch)
cargo tauri dev   (from src-tauri)
Answer each prompt (name → gender → city). Press Enter on the last field (or tap gender buttons).
```

What you should see:

Each question fades in one at a time on a dark fullscreen overlay.

After the last field: overlay fades to black.

HER speaks the first greeting — warm, personal, uses your name; if the city is ambiguous, she may ask which place you mean.

Words stream on screen as she speaks; waveform animates.

When HER starts speaking, the overlay fades away and the normal chat view appears beneath.

Second launch (without `rm`): no overlay; HER speaks the usual session opener with your saved name.

Most likely failure:

Fields appear stacked → check `frontend/onboarding.css` / `app.js` (`is-step-visible` toggles one step at a time).

`onboarding_complete` never fires → WebSocket must stay open; watch Python logs for exceptions in `_complete_onboarding`.

Pass condition: cinematic steps, warm spoken greeting, correct name; **no overlay** on second launch.

---

PHASE 4 — Proactive conversation

What to test: HER speaks first. Curiosity questions trigger on silence. No repeats.

Steps:

```
Open app → HER should speak within 3 seconds without you saying anything.
Respond briefly. Then go silent for 10 seconds.
HER should ask a question.
Answer it. Go silent again. She should ask a different question.
Close and reopen app next day (or change system clock) → different opener.
```

What you should see:

Terminal log: `[PROACTIVE] session opener generated`

Terminal log: `[PROACTIVE] lull detected after 8.2s, generating question`

Terminal log: `[PROACTIVE] gap selected: childhood`

SQLite: questions marked as asked (Phase 4 will introduce persistence — tables/paths TBD):

```
# Example once Phase 4 lands:
# sqlite3 data/profile.db "SELECT * FROM asked_questions;"
```

Most likely failure:

Opener fires before app is fully loaded → add 1.5s delay after WebSocket connect

Same question repeated → once Phase 4 ships, verify the gap tracker writes asked-question IDs to persistent storage.

Pass condition: opener heard, lull question heard, no repeat on second silence.

---

PHASE 5 — Intent + agents

What to test: HER can figure out what you need and build a tool to do it.

Steps:

```
Say: "Can you search the web for the latest news about OpenAI?"
Watch terminal for:
    "[INTENT] WHAT: web search / WHY: curiosity / online: approved"
    "[AGENT] no existing agent found, generating new one..."
    "[AGENT] agent written to agent_library/web_search_agent.py"
    "[AGENT] running in sandbox..."
HER should respond with actual news.
Say the same thing again → she should reuse the saved agent (no regeneration).
```

Most likely failure:

Agent generation fails syntax check → re-run when Phase 5 `agent_factory` module exists; validate generated Python in a sandbox.

Online call blocked → check intent approval / confidence gate once Phase 5 online layer exists.

Pass condition: web result returned, agent saved, reused on second ask.

---

PHASE 6 — Voice clone

What to test: HER collects audio, trains, switches voice.

Steps:

```
Talk naturally for 10+ minutes across multiple sessions.
Watch terminal: "[ABSORBER] X seconds of clean audio collected"
When 600s reached: "[CLONE] threshold reached, starting background training..."
Training takes 20-40 min. App stays fully usable during this.
When done: "[CLONE] training complete, switching to cloned voice"
```

What you should see:

HER's voice subtly changes to sound more like yours.

Kokoro used as fallback if cloned TTS fails on a chunk.

SQLite phase updated:

```
sqlite3 her/data/profile.db "SELECT current_phase FROM app_state;"
```

→ should show: `clone_active`

Most likely failure:

XTTS training crashes on 16GB → when Phase 6 `absorber` returns, check noise filter (low-quality samples bloat memory)

Voice sounds robotic → need more/cleaner audio samples

Pass condition: phase shows clone_active, voice is noticeably different.