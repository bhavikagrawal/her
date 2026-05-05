# PHASE_COMPLETE — HER

## What Phase 1 delivered

- `backend/voice/session.py` `VoiceSession`: 16 kHz capture, `silero-vad-lite` with barge-in, `whisper.cpp` **English-only STT** (`-l en`), Ollama `qwen2.5:7b` **streaming** to the UI, **Kokoro** English-only TTS, plus a non-English guard (blocks non-English transcripts and asks to repeat in English).
- `backend/main.py` spawns one **daemon** voice thread per WebSocket client; JSON event types: `voice_ready`, `user_transcript`, `assistant_reset`, `assistant_delta`, `her_speaking`, `error`.
- `frontend/`: user bubbles (right), HER (left) with live token deltas, bottom **waveform** when `her_speaking` is active.
- `scripts/download_voice_models.sh` + `data/models/kokoro/` for Kokoro weights; `data/models/whisper/README.txt` for medium model placement; `setup.sh` now prefers **Python 3.12**, reuses venv, runs Kokoro download, and ensures the Tauri **RGBA** icon exists.
- On-screen name is hardcoded **User** (per Phase 1 spec) for system-prompt testing.

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

Pass condition: full conversation, clean interruption, English-only (non-English is rejected with a prompt to repeat in English).

---

PHASE 2 — Memory

What to test: HER remembers across sessions.

Steps:

```
Start app. Say: "My favourite food is biryani and I hate mornings."
Say: "Remember that." Close app completely.
Reopen app. Say: "What do you know about my food preferences?"
```

What you should see:

HER mentions biryani without being told again.

SQLite personality snapshot updated (verify):

```
sqlite3 her/data/profile.db "SELECT * FROM personality_traits;"
```

Most likely failure:

ChromaDB collection not persisting → check: `her/data/chroma/` folder exists and has files

Memory not retrieved → check chroma_store.py query threshold (lower if needed)

Pass condition: biryani recalled correctly after full app restart.

---

PHASE 3 — Onboarding + greeting

What to test: first-launch form works. Greeting is spoken and feels cinematic.

Steps:

```
rm her/data/profile.db   (wipe profile to simulate first launch)
cargo tauri dev
Fill in form: name, address preference, gender, language. Press Enter on last field.
```

What you should see:

Each form field fades in one at a time on dark screen.

After last field: screen fades to black.

HER speaks the greeting — warm, personal, uses your name.

Words appear on screen as she speaks.

After greeting ends: chat UI fades in slowly.

Second launch (without rm): goes straight to chat, no form.

Most likely failure:

Form fields all appear at once → check onboarding.js fade-in timing (CSS transitions)

Greeting sounds generic → check greeting.py is passing name + gender + language to LLM

Pass condition: cinematic form, warm spoken greeting, correct name used, no form on second launch.

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

SQLite: questions marked as asked:

```
sqlite3 her/data/profile.db "SELECT * FROM asked_questions;"
```

Most likely failure:

Opener fires before app is fully loaded → add 1.5s delay after WebSocket connect

Same question repeated → check profile_gaps.py is writing to asked_questions table

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

Agent generation fails syntax check → check agent_factory.py validation output

Online call blocked → check online/decision.py confidence threshold

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

XTTS training crashes on 16GB → check absorber.py noise filter (low-quality samples bloat memory)

Voice sounds robotic → need more/cleaner audio samples

Pass condition: phase shows clone_active, voice is noticeably different.
