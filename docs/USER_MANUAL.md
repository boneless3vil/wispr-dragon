# Wispr Dragon — User Manual

Voice‑to‑text dictation with a Dragon‑style feel. This manual covers everything
you can *do* with Wispr Dragon: how to run it, the microphone and hotkey, how to
dictate (including spoken punctuation), voice commands, correction and
vocabulary, macros, every keyboard shortcut, and a full command‑line and
configuration reference.

For a first‑time install see the [README](../README.md) and
[quickstart](quickstart.md). This document assumes it's installed.

---

## 1. Two ways to run it

Wispr Dragon is really **two programs**, and which one you use decides which
features are available. This is the single most important thing to understand.

### A. Local desktop app — full feature set

Runs entirely on one machine (**Linux / WSLg**). Transcribes locally and injects
text into your focused window. **All** features work here: modes, voice
commands, spelling/numbers, macros, correction.

Run it **inside the Linux/WSL environment with the project venv activated** — not
from a Windows PowerShell prompt (a Windows `python` won't have the
dependencies, and this mode needs a Linux display):

```bash
cd ~/wispr_dragon && source venv/bin/activate
python -m wispr_dragon --ui      # floating dictation box (opens via WSLg)
python -m wispr_dragon           # headless (no window)
```

> This mode captures audio **locally in WSL**, which needs a working
> PulseAudio/PortAudio setup. If you're on the server + Windows‑client setup
> below, you don't need this mode at all — the Windows client captures on the
> Windows side and avoids that.

### B. Server + Windows client — the streaming setup

A **server** runs on Linux/WSL2 (does the GPU transcription); a lightweight
**Windows client** captures your microphone, streams audio over WebSocket, and
pastes the returned text into whatever Windows app is focused. This is the
recommended setup for dictating into Windows apps.

```bash
# On the Linux/WSL server:
python -m wispr_dragon --server

# On Windows (separate terminal):
python -m wispr_dragon.client
```

> **What the Windows client supports:** dictation (with spoken punctuation,
> auto‑capitalization, and your custom vocabulary — all applied on the server),
> the push‑to‑talk / toggle hotkey, text injection, the system‑tray indicator,
> and **"correct that."**
>
> **What it does _not_ support (yet):** voice commands and mode switches
> ("scratch that", "switch to command mode", spelling/numbers modes) and macros.
> Those run only in the **local desktop app** (A). In the client, saying them
> just dictates the words. Sections marked **(Local desktop app only)** below do
> not apply to the Windows client.

---

## 2. Getting started (server + client)

### Start the server (Linux / WSL2)

```bash
cd ~/wispr_dragon && source venv/bin/activate
python -m wispr_dragon --server
```

Wait for `WebSocket server listening`. Leave the terminal open — the server runs
until you press `Ctrl+C`.

To see the connection details a client needs (API key, LAN IP, port), run:

```bash
python -m wispr_dragon --server --print-key
```

### Start the client (Windows)

```powershell
python -m wispr_dragon.client
```

The client reads its settings from
`%LOCALAPPDATA%\WisprDragon\config.json` (see §10). On first run, if no server
URL / API key is set, a setup dialog asks for them.

Only **one** client can run at a time — a second instance is refused on purpose
(two clients would fight over the server's single connection, the hotkey, and
the microphone).

### Confirm it's connected

The client log shows `Connected to server` and `Server ready`. If the server is
new enough to support whole‑utterance transcription, you'll also see, when you
first speak, `Client uses utterance framing — VAD will trim, not split`.

---

## 3. The microphone & hotkey

### Push‑to‑talk vs toggle

| Mode | How it works | Set with |
|---|---|---|
| **PTT** (push‑to‑talk) | Records only while you **hold** the hotkey. | `"mode": "ptt"` (default) or `--mode ptt` |
| **Toggle** | **Tap** once to start, tap again to stop. | `"mode": "toggle"` or `--mode toggle` |

The default hotkey is **Right‑Ctrl** (`ctrl_r`). One press‑to‑release (PTT) or
one on/off cycle (toggle) is treated as **one utterance** and transcribed as a
single block — so a sentence with natural pauses stays whole instead of being
split into fragments.

Change the hotkey with the `"hotkey"` key in the client config (any
[pynput key name](https://pynput.readthedocs.io/) such as `ctrl_r`, `f9`, or a
single character). Change PTT↔toggle at runtime from the tray menu.

### The tray icon

The Windows client is a **headless tray app** — there is no main window by
design (a window would steal focus from the app you're dictating into). Its UI
is the system‑tray icon plus a right‑click menu:

- **A microphone icon** — white on a dark taskbar, black on a light one; it turns
  **red** while recording.
- **Right‑click menu:** recording state, Toggle/PTT mode, Settings…, Quit.

New tray icons are often hidden behind the taskbar's **`^` (show hidden icons)**
chevron — click it and drag the mic icon out to pin it.

---

## 4. Dictating

Speak naturally. Text is inserted into whatever window has focus when the
utterance completes (on release, in PTT; on the second tap, in toggle).

### Spoken punctuation & formatting

Say these words and they become symbols (works in the client too — applied on
the server):

| Say | You get | | Say | You get |
|---|---|---|---|---|
| "period" / "full stop" | `.` | | "open paren" | `(` |
| "comma" | `,` | | "close paren" | `)` |
| "question mark" | `?` | | "open quote" | `"` |
| "exclamation point/mark" | `!` | | "close quote" | `"` |
| "colon" | `:` | | "hyphen" | `-` |
| "semicolon" | `;` | | "dash" | ` -- ` |
| "new line" | line break | | "ellipsis" | `…` (`...`) |
| "new paragraph" | blank line | | "tab" | tab |

Automatic tidy‑up: spaces before `.,!?;:` are removed, and the first word of a
new sentence (after `.`, `!`, `?`) is capitalized. Words in your custom
vocabulary are re‑cased to their proper spelling (see §6).

### How text is injected (Windows client)

Two methods, chosen by the `inject_method` config key:

| `inject_method` | How | When to use |
|---|---|---|
| `paste` (default) | Copies the text to the clipboard and sends one **Ctrl+V**, then restores your previous clipboard. | Almost always. Robust and fast. |
| `sendinput` | Types the text character by character. | Only if an app refuses paste (rare — some terminals). |

`paste` is the default because on some systems a keyboard hook or peripheral
driver corrupts long bursts of synthesized keystrokes; a single Ctrl+V is
unaffected. If pasted text ever fails to appear, the app logs an error rather
than silently typing corrupted text — see Troubleshooting (§11).

---

## 5. Voice commands & modes — **(Local desktop app only)**

These work in the local desktop app (`--ui` or headless). They do **not** work
in the Windows client.

### Always‑on commands (any mode)

| Say | Does |
|---|---|
| "scratch that" | Undo the last phrase / drop the last segment |
| "correct that" | Open the correction window on the last utterance (see §6) |
| "go to sleep" | Enter **Sleep** — ignores everything except "wake up" |
| "wake up" | Leave Sleep, back to Dictation |
| "switch to command mode" | Enter **Command** mode |
| "switch to dictation mode" | Back to **Dictation** |
| "start spelling" / "spelling mode" | Enter **Spelling** mode |
| "stop spelling" | Back to Dictation |
| "start numbers" / "numbers mode" | Enter **Numbers** mode |
| "stop numbers" | Back to Dictation |

### The modes

| Mode | What it does |
|---|---|
| **Dictation** | Default. Speech becomes formatted text. |
| **Command** | Speech is matched against editing commands and your macros; nothing is dictated. |
| **Sleep** | The mic stays open but everything except "wake up" is ignored. The indicator shows **Standby** (amber). |
| **Spelling** | Speak letters to build a word. NATO words work ("alpha bravo charlie" → `abc`); "cap"/"capital" capitalizes the next letter; digits and spoken punctuation (period, dash, underscore, slash, at…) are supported. |
| **Numbers** | Number words become digits: "twenty three" → `23`, "three point one four" → `3.14`; a trailing "dollars" adds a `$`. |

### Command‑mode editing commands

After saying **"switch to command mode"**, these spoken phrases send keystrokes
to the focused app:

| Say | Key | | Say | Key |
|---|---|---|---|---|
| "select all" | Ctrl+A | | "go home" | Home |
| "copy that" | Ctrl+C | | "go end" | End |
| "paste that" | Ctrl+V | | "page up" | Page Up |
| "cut that" | Ctrl+X | | "page down" | Page Down |
| "undo that" | Ctrl+Z | | "press enter" | Enter |
| "redo that" | Ctrl+Shift+Z | | "press escape" | Esc |
| "save file" | Ctrl+S | | "press tab" | Tab |
| "find" | Ctrl+F | | | |

Say **"switch to dictation mode"** to return. (These are command‑mode only, not
always‑on.)

---

## 6. Correction & vocabulary

### "Correct that"

Say **"correct that"** (or "correct this") right after a phrase to fix it.

- **Windows client:** a dialog shows what was heard plus alternates and a
  freehand field. Choose or type the fix and click **Apply** — the client
  backspaces the previously injected text and retypes the correction, then
  teaches the fix to the server so it auto‑applies next time. Tick **Always
  apply** to make the correction permanent immediately.
- **Local desktop app:** the correction window shows the original with fuzzy
  suggestions from your dictionary, an editable field, and **Always apply**.

> Selection is by click or typing. (Selecting an alternate by *voice* — "choose
> 2" — is not wired up yet.)

### Commands & Vocabulary browser — (Local desktop app)

Open it from the desktop tray → **Commands & Vocabulary…**. Two tabs:

- **Commands** — create/edit/delete macros (see §7).
- **Vocabulary** — manage **Custom Words** (proper nouns, jargon; these get
  re‑cased correctly in dictation) and **Corrections** (wrong → right
  substitutions applied automatically).

Your dictionary lives at `~/.wispr_dragon/user_dictionary.json`.

---

## 7. Macros — **(Local desktop app only)**

A macro maps a spoken trigger to an action. Full details in
[docs/macros.md](macros.md); the essentials:

- **Where they live:** `~/.wispr_dragon/macros/*.yaml` (one macro per file). Ship
  examples are in `data/default_macros.yaml`.
- **Trigger:** a phrase, optionally with a `{placeholder}` that captures a word
  — e.g. `open {app}`.
- **Action types:**
  | Action | Field | Does |
  |---|---|---|
  | `launch` | `program:` (+ `args:`) | Launch a program on your PATH |
  | `text` | `content:` | Type a canned block of text |
  | `keystroke` | `keys:` | Send a key chord, e.g. `ctrl+s` |
  | `python_script` | `script:` | Run a **signed** script from `~/.wispr_dragon/scripts/` |

### Running a macro & the trust prompt

- In **Command** mode, a matched macro runs immediately.
- In **Dictation** mode, speaking a macro trigger pops a confirmation:
  **Yes, run it** / **No, type it** / **Trust always** (adds it to
  `~/.wispr_dragon/trusted.json` so it won't ask again).

### Macro security

Three layers protect you from a misheard phrase running something dangerous:

1. **Config switches** — `allow_program_launch`, `allow_python_scripts`,
   `allow_yaml_macros` (all on by default); `dictation_only` disables **all**
   macro execution.
2. **Admin lock** — password‑protect the policy so it can't be changed:
   `--admin-lock` / `--admin-unlock`, inspect with `--security-status`.
3. **Script signing** — `python_script` macros must be signed with
   `--sign-script <path>` (SHA‑256), run sandboxed in a subprocess with a 30 s
   timeout. Clear trusted programs/scripts with `--clear-trust`.

---

## 8. Keyboard shortcuts

### Dictation box window (local desktop app)

| Shortcut | Action |
|---|---|
| **Enter** (or Numpad Enter) | Post text to the active window |
| **Esc** | Cancel — close without posting |
| **Ctrl+L** | Clear the current text |

Buttons in the box: **Pause Mic / Resume Mic**, **Post**, **Clear**, **Cancel**.
(Pause freezes the elapsed timer; Clear resets it.)

### Windows client

The client's only "shortcut" is the **dictation hotkey** (Right‑Ctrl by
default, §3). Everything else is on the tray menu.

---

## 9. Command‑line reference

### Server / desktop — `python -m wispr_dragon [flags]`

| Flag | Values | Meaning |
|---|---|---|
| `-v`, `--verbose` | | Debug logging |
| `--config PATH` | | Use a specific config file |
| `--model` | e.g. `small.en`, `medium.en`, `large-v3` | Override model size |
| `--device` | `cuda`, `cpu` | Override compute device |
| `--compute-type` | `auto`, `float16`, `int8`, `int8_float16`, `bfloat16`, `float32` | Precision (`int8_float16` halves VRAM vs float16) |
| `--beam-size` | int | Higher = more accurate, slower (default 10) |
| `--no-vad` | | Disable voice‑activity detection |
| `--dictation-only` | | Disable all macros/commands |
| `--server` | | Run as the WebSocket server |
| `--print-key` | | Print the client connection details and exit |
| `--ui` | | Launch the floating dictation box |
| `--inject-method` | `auto`, `xdotool`, `clipboard`, `wl-clipboard`, `clip.exe`, `print` | Injection backend (local desktop; auto‑detected) |
| `--sign-script PATH` | | Sign a Python macro script |
| `--admin-lock` / `--admin-unlock` | | Enable/disable the password admin lock |
| `--security-status` | | Show the current security policy |
| `--clear-trust` | | Clear trusted programs/scripts |

### Windows client — `python -m wispr_dragon.client [flags]`

| Flag | Values | Meaning |
|---|---|---|
| `--config PATH` | | Use a specific client config file |
| `--list-devices` | | List audio input devices and exit |
| `--no-inject` | | Print transcripts instead of typing them (safe test mode) |
| `--mode` | `ptt`, `toggle` | Override hotkey mode (else config, else `ptt`) |
| `--no-tray` | | Run headless, without the tray icon |

**Tip:** `--list-devices` shows the index for each mic; put that number in the
client config's `"device"` field to force a specific microphone.

---

## 10. Configuration reference

### Server / desktop — `~/.wispr_dragon/config.yaml`

**audio**
| Key | Default | Meaning |
|---|---|---|
| `sample_rate` | 16000 | Capture rate (Hz) |
| `vad_threshold` | 0.5 | Speech‑detection sensitivity (0–1) |
| `silence_duration_ms` | 900 | Trailing silence that ends a segment (VAD mode) |
| `min_speech_duration_ms` | 250 | Shortest sound treated as speech |
| `max_utterance_seconds` | 25 | Safety cap: force‑finalize a held hotkey after this long |
| `source` | `pulseaudio` | `pulseaudio` or `network` |

**engine**
| Key | Default | Meaning |
|---|---|---|
| `backend` | `auto` | `auto`, `faster-whisper`, `openai-whisper`, `openai-api` |
| `model_size` | `small.en` | Whisper model |
| `device` | `auto` | `auto`, `cuda`, `cpu` |
| `compute_type` | `auto` | Precision |
| `language` | `en` | Language code |
| `beam_size` | 10 | Accuracy vs speed |
| `initial_prompt` | "" | Context to bias recognition |
| `hotwords` | "" | Comma‑separated terms to favor |

**correction:** `auto_apply_threshold` 3 · `fuzzy_match_score` 85 ·
`max_hotwords` 100 · `save_audio_segments` false.
**security:** `allow_python_scripts`, `allow_yaml_macros`, `allow_program_launch`
(all true) · `dictation_only` false.
**server:** `host` 0.0.0.0 · `port` 8765 · `api_key` "" · `max_connections` 1.
(When `api_key` is empty the server accepts unauthenticated local connections and
warns; set one with `--print-key` for anything beyond localhost.)

### Windows client — `%LOCALAPPDATA%\WisprDragon\config.json`

```json
{
  "server_url": "ws://localhost:8765",
  "api_key": "",
  "sample_rate": 16000,
  "device": null,
  "mode": "ptt",
  "hotkey": "ctrl_r",
  "inject_method": "paste"
}
```

| Key | Meaning |
|---|---|
| `server_url` | WebSocket URL of the server (`ws://host:8765`) |
| `api_key` | Must match the server's key (blank if the server has none) |
| `device` | Mic index from `--list-devices`, or `null` for the system default |
| `mode` | `ptt` or `toggle` |
| `hotkey` | pynput key name (e.g. `ctrl_r`, `f9`) |
| `inject_method` | `paste` (default) or `sendinput` |

---

## 11. Troubleshooting

**Pasted text is garbled — repeated letters, dropped words**
Something on your system corrupts synthesized keystrokes. Make sure
`inject_method` is `paste` (the default). If it says an error about not being
able to take the clipboard, another app is holding it — close clipboard managers.

**Dictation comes back as fragments** ("a result." / "is due to.")
The server is too old to support whole‑utterance transcription, so it's falling
back to splitting on pauses. Restart the server from current code; when the
client connects you should see `Client uses utterance framing`.

**Nothing types / it won't record**
- Wrong microphone: run `python -m wispr_dragon.client --list-devices`, find your
  mic's index, and set `"device"` to that number.
- A second client is running: only one is allowed — the second is refused. Quit
  the extra one.
- Focus: text is injected into whatever window is focused. Click into your target
  app first.

**No tray icon**
You launched with `--no-tray`, or the icon is behind the taskbar's `^` chevron.
Drop `--no-tray` and check the hidden‑icons flyout.

**Server error `Library libcublas.so.12 is not found` on first speech**
The CUDA‑12 runtime libs aren't installed. Install the GPU extra:
`pip install -e ".[server,cuda]"` (NVIDIA). The engine preloads them at startup.

**`ModuleNotFoundError: No module named 'wispr_dragon'` on Windows**
Install the package into the client's environment (`pip install -e .` from the
repo), or ensure the repo is on `PYTHONPATH`.

---

## 12. Where your data lives

| Path | What |
|---|---|
| `~/.wispr_dragon/config.yaml` | Server/desktop settings |
| `~/.wispr_dragon/user_dictionary.json` | Custom words + corrections |
| `~/.wispr_dragon/commands.yaml` | Saved commands |
| `~/.wispr_dragon/macros/*.yaml` | Your macros |
| `~/.wispr_dragon/scripts/` | Signed macro scripts (+ `.manifest.json`) |
| `~/.wispr_dragon/trusted.json` | Programs/scripts you chose to trust |
| `~/.wispr_dragon/logs/` | Logs |
| `%LOCALAPPDATA%\WisprDragon\config.json` | Windows client settings |

---

*Some advanced items are intentionally omitted here because they are not yet
wired up for end users (voice selection inside the correction dialog, the config
settings GUI, and dictation‑mode capitalization voice commands). They may appear
in a future release.*
