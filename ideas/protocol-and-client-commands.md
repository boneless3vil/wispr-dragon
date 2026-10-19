# Shared protocol module + client-side command engine — design

**Status:** proposed 2026-10-19 (architect), grounded in `test` @ `c40507c`.
**Decided by Jon:** this is the next big work item. The server becomes a pure
recognizer and never sends anything executable; modes, commands, "scratch
that", spelling/numbers and macros run on the client; the `--ui` desktop path is
retired once its parts live in the client. Backward compatibility is kept at
every phase.

## 0. What the code says (findings that shape this design)

- **The server already only recognizes, but it formats every utterance.**
  `PipelineRunner._transcribe_and_format` calls `post_processor.process(text)`
  with `apply_formatting` defaulting to True. `PostProcessor.process(text,
  apply_formatting=False)` already exists.
- **JSON is built inline everywhere.** Server: `ready`, `utterance_ack`,
  `pong`, `correction_learned`, `transcript` (×2), `error`. Client: the
  `listen()` if-chain and the `app.py` dicts for `utterance_start` /
  `utterance_end` / `learn_correction`.
- **The client can import `modes/` and `macros/` as they stand** (base deps
  only: `pyyaml`, `rapidfuzz`, stdlib; `bcrypt` is imported lazily). Three
  blockers:
  1. `ui/mic_state.py` and `ui/confirm_command.TrustManifest` live under
     `wispr_dragon.ui`, which `tests/test_import_isolation.py` and the
     PyInstaller spec both ban.
  2. `modes/` and `correction/` have no `__init__.py` (namespace packages).
  3. `packaging/wispr_dragon_client.spec` bundles only `assets/*.png` — a frozen
     client would have no `data/default_commands.yaml`.
- **`ScriptRunner` runs `sys.executable`**, which in the frozen client is
  `WisprDragonClient.exe`, not Python.
- **`ConfirmationDialog.show_and_ask` uses `exec()`**, which wedges the qasync
  loop (the lesson recorded in `app.call_outside_task`).
- **Macros only match in COMMAND mode** (`ModeManager._handle_command`). The
  "confirm in dictation mode" branches in `main.handle_macro` and
  `UIController._run_macro` are unreachable, yet USER_MANUAL §7 describes them
  as live behaviour.
- **Toggle mode sends one utterance per toggle session** (in 25 s pieces), so an
  always-on command fires only if it is the whole session.
- **The client feeder sends audio and control frames before `ready` arrives.**
- **The threat already exists today:** over `ws://`, a MITM can send text
  containing `\n`, and pasting that into a focused terminal runs it. TLS is
  worth having whether or not commands move.

## 1. Goals / non-goals

**Goals:** one stdlib-only `wispr_dragon/protocol.py` used by both sides; a
version + feature handshake; modes/commands/"scratch that"/spelling/numbers/
macros on the client with the server sending only text and data; per-utterance
formatting control; pinned TLS; old↔new compatibility in every direction at
every phase.

**Non-goals:** streaming partials and voiceprint (messages reserved only);
moving off the websockets legacy API; multi-client; building the floating box.

## 2. Protocol module: `wispr_dragon/protocol.py`

Stdlib only (`json`, `dataclasses`, `typing`); a test asserts importing it loads
no third-party module.

**Constants**

- `PROTOCOL_MAJOR = 1`, `SUPPORTED_MAJORS = frozenset({1})`. Today's wire is
  protocol 1; a `ready` without `protocol` means 1. No minor number — minor
  capability is expressed only through feature flags.
- Audio: `SAMPLE_RATE = 16000`, `CHANNELS = 1`, `SAMPLE_FORMAT = "s16le"`,
  `FRAME_SAMPLES = 480`, `FRAME_BYTES = 960`.
- Limits (moved from the server): `MAX_MESSAGE_BYTES = 256 KiB`,
  `MAX_CORRECTION_CHARS = 200`; new `MAX_ID_CHARS = 64`, `MAX_ALTERNATIVES = 9`,
  `MAX_VOCAB_ITEMS = 5000`.
- Close codes: `CLOSE_INTERNAL = 1011`, `CLOSE_ALREADY_CONNECTED = 4000`,
  `CLOSE_UNAUTHORIZED = 4001`, new `CLOSE_INCOMPATIBLE = 4002` with reason
  `protocol_major` | `audio_format` | `bad_hello`.
- Features: `utterance` (existing); `hello`, `utterance_mode`, `raw`,
  `alternatives`; `vocab_sync` (later); `partial`, `speaker_gate` (reserved —
  `speaker_gate` is the name the voiceprint design already uses).
- Wire modes: `dictation | command | spelling | numbers | sleep`.

**Message shape:** one frozen dataclass per message.

```python
@dataclass(frozen=True)
class UtteranceStart(ClientMessage):
    TYPE: ClassVar[str] = "utterance_start"
    id: str | None = None
    mode: str | None = None            # FEATURE_UTTERANCE_MODE
```

`Message.to_dict()` / `to_json()` omit None fields. `from_dict()` type-checks
against the annotations (`str`, `bool`, `int` but not bool, `float` accepting
int, `list[str]`, nested `AudioFormat`) and raises `ProtocolError`. Entry
points `parse_client(raw)` / `parse_server(raw)` return a message or
`UnknownMessage(type, data)`.

**Tolerance rules (normative)**

1. Unknown `type`: log and ignore; never close.
2. Unknown fields: ignore.
3. Absent and `null` are the same (None).
4. A known field with the wrong type rejects that message (log, ignore); never
   close — except a malformed `hello`, which closes 4002 `bad_hello`.
5. An unknown `mode` value is treated as `dictation`, with a warning.
6. Non-object JSON, and binary frames server→client, are ignored.
7. Adding a message/field/feature is not a version bump; renaming or removing a
   field, or changing its meaning, bumps the major.
8. Client→server optional fields are honoured whenever the server understands
   them. Server→client optional fields/messages are sent only when negotiated
   (`ready.features ∩ hello.features`). **A connection that never sends `hello`
   gets exactly today's wire.**

**Message table**

| Dir | type | Fields (`?` optional) | Gate | Since |
|---|---|---|---|---|
| S→C | `ready` | server_version, features[], protocol?, audio?{rate,channels,format} | — | baseline; protocol/audio P2 |
| C→S | `hello` | protocol, client_version, platform (`sys.platform`), features[], audio{rate,channels,format} | server advertises `hello` | P2 |
| C→S | binary | s16le mono PCM, 480-sample frames | — | baseline |
| C→S | `utterance_start` | id?, mode? | `utterance`; mode needs `utterance_mode` | baseline; mode P2 |
| S→C | `utterance_ack` | id? | `utterance` | baseline |
| C→S | `utterance_end` | id?, mode? (late-binding override) | as above | baseline; mode P2 |
| S→C | `transcript` | text, final, language, duration, id?, utterance?, continued?, mode? (applied), raw?, alternatives?[] | mode→`utterance_mode`; `raw`; `alternatives` | baseline; P2 |
| C→S | `pause` / `resume` | — | — | baseline |
| C↔S | `ping` / `pong` | ts? | — | baseline |
| C→S | `learn_correction` | wrong, correct, always? | — | baseline |
| S→C | `correction_learned` | wrong, correct | — | baseline |
| S→C | `error` | code, message | — | baseline |
| C→S | `vocab_list` | req | `vocab_sync` | P8 |
| S→C | `vocab` | req, custom_words[], corrections[{wrong,correct,frequency}], phrases{} | `vocab_sync` | P8 |
| C→S | `vocab_add` | req, kind (`word`\|`correction`\|`phrase`), word? / wrong?, correct?, always? / phrase?, replacement? | `vocab_sync` | P8 |
| C→S | `vocab_remove` | req, kind, key | `vocab_sync` | P8 |
| S→C | `vocab_ack` | req, ok, error? | `vocab_sync` | P8 |
| S→C | `partial` | id, seq, text | `partial` | reserved |
| S→C | `utterance_rejected` | id, reason | `speaker_gate` | reserved |

**Examples**

```json
{"type":"ready","server_version":"1.1.0","protocol":1,
 "features":["utterance","hello","utterance_mode","raw","alternatives"],
 "audio":{"rate":16000,"channels":1,"format":"s16le"}}
{"type":"hello","protocol":1,"client_version":"1.1.0","platform":"win32",
 "features":["utterance_mode","raw","alternatives"],
 "audio":{"rate":16000,"channels":1,"format":"s16le"}}
{"type":"utterance_start","id":"9f2c41","mode":"spelling"}
{"type":"transcript","text":"Their","final":true,"language":"en","duration":0.9,
 "id":"9f2c41","utterance":true,"continued":false,"mode":"dictation",
 "raw":"Their.","alternatives":["There","They're","Their"]}
```

**Handshake order:** the server still sends `ready` first (old clients keep
working). The client sends `hello` only if `ready.protocol` is present, so old
servers never receive it. The client feeder waits on a `session_ready` event
(set after `ready` is processed and `hello` sent; 3 s timeout fallback) before
sending anything — closing today's race where `utterance_start` can precede
`ready`.

**Close 4002 on the client** behaves like 4001: stop reconnecting, status
`incompatible`, one tray notification. Never a reconnect storm.

## 3. Client command engine

### 3.1 Imported, moved, never imported

- **Imported as-is:** `modes/` (`mode_manager`, `orchestrator`, `transforms`,
  `command_mode`, `triggers`), `macros/` (`macro_runner`, `security`,
  `script_runner`), `correction/alternates.py`.
- **Moved out of `ui/`** (re-export shims left behind):
  `ui/mic_state.py` → `modes/mic_state.py`; `TrustManifest` →
  `macros/trust.py`; `icons.icon_for_mic_state` imports from the new location.
- **Add** empty `modes/__init__.py` and `correction/__init__.py`.
- **Never imported by the client:** `post_processor`, `dictionary`, `hotwords`
  (server-only).

### 3.2 ModeManager returns actions

New `modes/actions.py` (frozen dataclasses): `InsertText(text)`, `Undo()`,
`OpenCorrection(target: str|None)`, `Keystroke(chord)`,
`RunMacro(macro_id, args: tuple[tuple[str,str],...], spoken)` (`macro_id` = the
normalized trigger), `SetMode(mode)`, `UnknownCommand(name)`.

- **`ModeManager.decide(text, raw=None) -> list[Action]`** mutates only mode
  state. Always-on commands, commands and macros match against `raw or text`,
  so a learned correction can neither break nor forge a command. The
  `dictation_only` filter stays (defence in depth). The constructor takes
  `registry: CommandRegistry | None` (no global `_registry`), `macro_index`
  (anything with `find_macro()` / `get(id)`; `MacroRunner` gains `get`), and
  `dictation_only`.
- **`process_text()` stays as a compatibility shim** for `main.py` and
  `UIController`: it calls `decide()` and dispatches to the registered handlers
  exactly as today. Deleted in P9.
- **Add `"correct this"` to `ALWAYS_ON_COMMANDS`.**
- **`DictationOrchestrator`:** `post_processor` becomes optional; new signature
  `handle_transcript(text, *, raw=None, applied_mode=None) -> TranscriptOutcome`;
  `TranscriptOutcome` gains `actions`, with `text` / `consumed` becoming derived
  properties so existing callers are unchanged. The mode transform applies to
  `InsertText`; if `applied_mode` differs from the mode at handling time and the
  current mode is spelling or numbers, it transforms `raw` instead (see the
  formatting race in 3.6).

### 3.3 Executor: `wispr_dragon/client/executor.py`

```python
class OutputSink(Protocol):
    def insert(self, text: str) -> bool: ...
    def undo_last(self) -> bool: ...
    def replace_last(self, text: str) -> bool: ...
    def last(self) -> "HistoryEntry | None": ...
```

**`InjectorSink`** owns the history — a deque of 20
`HistoryEntry{text, payload_len, raw, applied_mode, alternatives, utterance_id,
focus_token}` replacing `_last_injection_text/_len`. `insert` does
`sanitize_text`, the trailing-space rule (moved from `app._on_transcript`),
injects and records. `undo_last` calls `replace_last(payload_len, "")` only if
`focus_token` is unchanged, otherwise notifies "focus changed — not undoing".
`focus_token` comes from a new `windows_injector.foreground_window()`
(`GetForegroundWindow`); elsewhere it is None and the check is skipped.

**`ActionExecutor(sink, injector, macros, policy, ui, hotkey)`** runs on the
asyncio loop; Qt work is scheduled with `loop.call_soon` (the existing
pattern); macro execution goes through `loop.run_in_executor` (a launch or
script can block up to 30 s).

- `InsertText` → `sink.insert`. `Undo` → `sink.undo_last`.
- `OpenCorrection` → the dialog for `sink.last()`, using `entry.alternatives`
  and falling back to `synthesize_alternates(entry.text)` (`CorrectionDialog`
  gains `alternates=`). On apply: `sink.replace_last`, then
  `learn_correction(wrong=entry.raw or entry.text, …)` — only when
  `applied_mode` is None or `dictation`.
- `Keystroke` → `injector.send_keys(chord)` with a **modifier-hotkey guard**:
  if the hotkey is a modifier (default `ctrl_r`) and physically held, defer
  until release (2 s cap, then drop and notify) — otherwise "press enter" would
  become Ctrl+Enter during a PTT re-press.
- `RunMacro` → policy check (§5) → non-modal confirm if needed →
  `MacroRunner.execute` in a thread.
- `SetMode` → `mic_state.set_asleep(...)`, update the tray mode label.

**Routing order in `app._on_transcript`:** an open correction dialog gets speech
first (existing `_route_to_correction`), then `orchestrator.handle_transcript`,
then `executor.execute`.

### 3.4 One keystroke implementation

- **New `wispr_dragon/keychords.py`** (stdlib): `parse_chord("ctrl+shift+z") ->
  KeyChord(mods, key)`. Owns the validation regex (today copied 3×) and the
  canonical key names — today's `_PYNPUT_KEY_MAP` names plus the xdotool
  aliases `Return`, `Page_Up`, `Escape`.
- **`WindowsTextInjector.send_keys(chord)`:** VK table + `VkKeyScanW` for
  characters, through the existing `_send`; a pure `_chord_inputs()` keeps it
  testable.
- **`output/text_injector.TextInjector.send_keys`:** `xdotool key
  --clearmodifiers`.
- **Delete** `main._validate_keystroke` and the `subprocess` call in
  `handle_keystroke`; the xdotool code in `MacroRunner._execute_keystroke`
  (which calls `text_injector.send_keys` instead); `UIController._send_keystroke*`
  and `_PYNPUT_KEY_MAP`.
- Future injectors (ydotool, CGEvent) implement the same three methods:
  `inject`, `replace_last`, `send_keys`.

### 3.5 Client-side data

Root is `default_config_dir()` (`%LOCALAPPDATA%\WisprDragon` on Windows):
`commands.yaml`, `macros\*.yaml`, `scripts\*.py` + `scripts\.manifest.json`,
`trusted.json`, `security.lock`, `server_cert.pem` (pinned trust anchor).
Policy lives in a `"security": {...}` object in `config.json`, passed to
`SecurityPolicy` as `security_cfg` (it already accepts any attribute bag and
resolves non-booleans to the restrictive value).

### 3.6 Mic state, tray, per-utterance mode

- **Mic state:** on a hotkey change, `set_capturing(active)` then
  `set_asleep(mode == SLEEP)` — the same dance as `UIController._toggle_mic`;
  without it PTT would clobber STANDBY.
- **Tray:** icon from `icon_for_mic_state` (gray off / red hot / amber
  standby); a "Mode ▸ Dictation/Command/Spelling/Numbers" radio submenu
  (DragonBar parity); a "Go to sleep / Wake up" item.
- **Telling the server the mode:** `UtteranceStart(id, mode)` on press,
  `UtteranceEnd(id, mode)` on release (late binding) — only if the server
  supports `utterance_mode`. The server applies `end.mode or start.mode or
  "dictation"` and echoes the applied mode in `transcript.mode`.
- **Formatting race:** if the echoed mode differs from the client's current
  mode, the orchestrator uses `raw` (3.2).
- **Against a legacy server** formatting is always on. Spelling and numbers
  still work with minor loss (a spoken "period" while spelling becomes "." on
  the server and is dropped by the tokenizer). Document this.

## 4. Server changes

- **`websocket_server.py`:** per-connection `ConnState` (`hello`,
  `client_features`, `negotiated`, utterance mode); dispatch on parsed message
  classes. `hello` checks: major not in `SUPPORTED_MAJORS` → 4002
  `protocol_major`; audio ≠ (server `config.audio.sample_rate`, 1, `s16le`) →
  4002 `audio_format` (today a 48 kHz client silently produces garbage). A
  second `hello` is ignored.
- **`_finalize_utterance`** calls `pipeline_runner.recognize(audio, mode=…,
  alternatives="alternatives" in negotiated)` on the engine thread
  (alternatives use the live dictionary, serialized with `learn_correction`)
  and emits `mode` / `raw` / `alternatives` only when negotiated.
- **`pipeline_runner.py`:** `Recognition(text, raw, alternatives)`;
  `recognize(audio, *, mode="dictation", trim=True, alternatives=False) ->
  Recognition | None`; `process_utterance()` becomes a thin wrapper (keeps the
  voiceprint plan and existing tests valid); `_transcribe_and_format(audio,
  mode)` sets `apply_formatting = mode == "dictation"` (`sleep` treated like
  `command`). Later, server-internal only: per-mode prompts (letters for
  spelling, digits for numbers).
- **`learn_correction` / `vocab_*` validation:** reject any character with
  `ord < 0x20`; enforce length and count caps.
- **`ready`** adds `protocol` and `audio` and the features `hello`,
  `utterance_mode`, `raw`, `alternatives`.
- The legacy VAD path is unchanged.

## 5. Security

**Threat model**

| Attacker | Today | After |
|---|---|---|
| LAN sniffer on `ws://` | Reads dictation and the API key | Nothing (TLS) |
| Holder of a sniffed key | Takes the 4000 slot (DoS); poisons the dictionary | Same until TLS; poisoning can't forge commands (matched on `raw`); control characters rejected |
| MITM / compromised server | Arbitrary text incl. `\n` into the focused app | Can also *speak* command phrases → built-in keystrokes and the user's own macros; can never supply chords, programs, scripts or args. T2 needs a trusted transport, which keeps a MITM out |

**The executor is the security boundary.**

| Tier | Actions | Allowed when |
|---|---|---|
| T0 | InsertText, Undo, OpenCorrection, SetMode | Always (today's dictation-safe set) |
| T1 | Keystroke; macro `text` / `keystroke` | Not `dictation_only`; `allow_yaml_macros` for macros |
| T2 | macro `launch`, `python_script` | All of: `allow_program_launch` / `allow_python_scripts`; a trusted transport (`wss` with a pin, a CA-verified cert, or `ws` to loopback 127.0.0.1 / ::1 / localhost — covers WSL localhost forwarding); a program captured through a placeholder must be in `trusted.json` or confirmed every time (captures are already `[\w\s]+`); scripts match the SHA-256 manifest; in a frozen build an absolute `python_interpreter` is configured, else scripts are disabled with a notice |

- Parameters are always local: chords, programs, scripts and args come only
  from client-local YAML.
- The confirm dialog is a new non-modal `client/confirm_dialog.py` (`open()` +
  `finished`).
- Client admin CLI: `--sign-script`, `--security-status`, `--admin-lock`,
  `--admin-unlock`; the handlers move from `main.py` into `macros/admin_cli.py`
  taking `(user_dir, security_cfg)`.
- Invariant test: the set of server→client message types equals an allowlist —
  adding an executable message type must break a security test on purpose.

**TLS (P4): pin first, then use the cert as the trust anchor**

- **Server** — new `server/tls.py` (`cryptography`, added to the `server` and
  `dev` extras). `--print-key` generates, if no cert is configured,
  `~/.wispr_dragon/tls/server.{crt,key}` (key 0600; EC P-256, 10 years; SAN =
  hostname + LAN IP + localhost; SKI/AKI; `basicConstraints`) and prints
  `wss://IP:tls_port` plus `"tls_fingerprint": "SHA256:AB:…"`. New config:
  `server.tls_port` (0 = today's single listener, so existing TLS setups don't
  break) and `server.plaintext` (default true for now). With `tls_port` set,
  two listeners share one handler, so `max_connections=1` holds across both.
- **Client** — new `client/tls_pin.py` (stdlib). If the cached
  `server_cert.pem` has the configured fingerprint, use it; otherwise do a
  TLS-only probe (`CERT_NONE`, no HTTP), read `getpeercert(binary_form=True)`,
  compare with the configured fingerprint, and cache the PEM. Connect with
  `ssl.SSLContext(PROTOCOL_TLS_CLIENT)`, `CERT_REQUIRED`,
  `check_hostname=False`, `load_verify_locations(cadata=pem)` — not
  `create_default_context`, because Python 3.13 enables `VERIFY_X509_STRICT`.
  Re-check the peer fingerprint after the handshake. The `Authorization`
  header is never sent to an unpinned peer. On mismatch: stop reconnecting and
  notify with both fingerprints. `wss://` without a fingerprint uses normal CA
  verification. The setup dialog and `validate_setup` gain a fingerprint field.
- **Ordering:** TLS (P4) ships before macros (P7); because the T2 gate is
  enforced at runtime, phase order cannot open a window. T0/T1 over plaintext
  add nothing beyond what text injection already allows.

## 6. Phases (each a PR, each shippable on its own)

**P1 — Extract the protocol, no behaviour change.** New `protocol.py`;
`websocket_server.py`, `websocket_client.py` and `app.py` build and parse
through it (client `CLOSE_*` names re-exported; `_SILENCE_FRAME` from
`FRAME_BYTES`; `_enqueue_control` picks its victim with `isinstance(it,
bytes)`). Tests: `tests/test_protocol.py` (round-trip, unknown type, unknown
field, wrong type, omit-None); golden fixtures
`tests/fixtures/protocol/baseline/*.json`, one per message, both directions,
each satisfying `parse → to_dict == fixture`; server emissions captured in e2e
have exactly the fixture key sets; import isolation (protocol loads only
stdlib); existing e2e untouched and green.

**P2 — Server handshake + transcript metadata.** `ConnState`,
`hello`/4002, `recognize(mode, alternatives)`, new `ready` fields, input
validation. Freeze `tests/legacy/server_v1_0.py` and `client_v1_0.py` (copies
at `c40507c`, never edited). New `tests/test_protocol_compat.py`: the
{legacy, new}² matrix dictates a round trip; legacy-client transcripts carry
exactly the baseline keys; 4002 for a wrong major, wrong audio and a malformed
hello; a `command`-mode utterance gets `apply_formatting=False` (spy
post-processor); alternatives come from the dictionary; control characters in
`learn_correction` rejected. Add v1.1 fixtures.

**P3 — Client handshake.** Send `hello`; gate the feeder on `session_ready`;
handle 4002 (an `incompatible` flag, no reconnect); use `alternatives` and
`raw` in correction (`CorrectionDialog(alternates=)`); always send
`mode="dictation"`. Tests: 4002 → exactly one connection attempt in 5 s;
`hello` only when `ready.protocol` is present; correction uses server
alternatives; the matrix still passes.

**P4 — TLS.** New `server/tls.py`, `client/tls_pin.py`; `config.py`
(`tls_port`, `plaintext`) together with `tests/test_config_validation.py`;
`main.format_client_setup`, the setup dialog, `pyproject`. Tests: wss with the
correct pin dictates; with a wrong pin the server sees zero `Authorization`
headers and the client stops; the plaintext listener still works; fingerprint
formatting accepts colons and either case.

**P5 — Actions refactor** (desktop paths migrate; client unchanged).
`modes/actions.py`, `decide()`, the compatibility shim, registry injection, the
orchestrator changes, `keychords.py`, `send_keys` on both injectors, deleting
the three keystroke copies, moving `mic_state` / `TrustManifest`, the
`__init__` files. Tests: `decide()` returns the expected actions for every
always-on command, sleep and `dictation_only`; existing `test_mode_manager`,
`test_orchestrator`, `test_ui_controller` pass through the shim; new
`test_keychords.py`; `_chord_inputs` produces the right VK sequence; import
isolation covers `modes.*`, `macros.*`, `keychords` (no heavy modules, no
PyQt6).

**P6 — Client engine, T0.** `client/executor.py` (`InjectorSink`, focus
token), engine wiring in `app.py`, the tri-state tray, the mode submenu,
sending the mode on start and end. Tests in `test_client_command_engine.py`
with `FakeInjector`: "scratch that" → `replace_last(n, "")`; "start spelling"
then "a b c" → "abc"; race (applied ≠ current mode → `raw` used); sleep
honours only "wake up" and the tray shows STANDBY; undo refused after a focus
change. E2E with a scripted FakePipeline: after "start spelling", the next
`recognize()` gets `mode=spelling`.

**P7 — Client keystrokes and macros (T1/T2).** Policy, confirm dialog, the
modifier guard, macros off the loop, the client admin CLI,
`ScriptRunner(interpreter=)`; spec `includes=["assets/*.png","data/*.yaml"]`
plus hidden imports; USER_MANUAL §1/§5/§7. Tests: table-driven policy matrix
(transport × `dictation_only` × `allow_*` × placeholder trust); a slow macro
doesn't delay a concurrent transcript; frozen build without an interpreter
disables scripts; the guard defers while the modifier is held; a spec test
asserts `data/*.yaml` is bundled.

**P8 — Vocabulary sync.** The `vocab_*` messages, server handlers with caps,
and a client "Commands & Vocabulary" dialog (`client/vocab_dialog.py`; the
Commands tab edits client-local macros). Tests: CRUD round-trip, caps,
unauthorized kinds rejected.

**P9 — Retire `--ui` and the headless loop.** Prerequisites: a Linux client
injector (ydotool) and the floating box. Delete `process_text` / the handlers,
`main.py`'s loop and the desktop `ui/` path.

## 7. Risks and open questions

**Risks**

- **Mode race** — mitigated by late binding on `utterance_end`, the echoed
  `transcript.mode`, and `raw`. Switching spelling → dictation can't
  re-format, so the user sees unformatted text in that rare case.
- **Keystrokes while PTT is held** — the modifier guard.
- **Undo/correct into the wrong window** — the focus token (this also hardens
  today's "correct that").
- **Frozen build packaging** — the `sys.executable` script problem and the
  missing `default_commands.yaml`, both handled in P7.
- **TLS** — Python 3.13's strict X.509 mode; the new `cryptography` server
  dependency.
- **Linux desktop users** — retiring `--ui` before a Linux client injector
  exists would strand them (hence P9's prerequisites).

**Open questions for Jon**

1. **Dragon "Normal mode":** should built-in editing commands and macros fire
   in Dictation mode when spoken as the whole utterance (first-use
   confirmation for macros), with Command mode kept as the strict option?
   Today they fire only in Command mode, and USER_MANUAL §7 describes a
   dictation-mode prompt the code never reaches. Recommendation: yes.
2. **Toggle mode:** a command only works if it is the entire toggle session.
   Add opt-in pause segmentation on the server inside a toggle session (Dragon
   finds commands by pauses), or accept "one command per press"?
3. **Sleep:** should pressing the hotkey while asleep wake the mic, like
   Dragon's mic button? Recommendation: yes.
4. **Plaintext listener:** when should `server.plaintext` default to off?
   Proposal: the release after P4, once the installed exe has been rebuilt.

## 8. Changes needed in `ideas/windows-floating-dictation-box.md`

- Rewrite "Architectural consequence": the command engine does **not** go
  through the server — it runs in the client (`modes/` + `ActionExecutor`); the
  server only gains utterance mode, `raw` and `alternatives` (P2). Point to
  P2/P5–P7 here instead of a "larger server + protocol change".
- The box is an `OutputSink`: undo and correct edit the box's segments, Post
  calls `injector.inject(buffer)`, and `Keystroke` actions target the box
  widget while it has focus.
- "Live transcription streams into the box" needs `partial`, which is reserved
  here and not built; until then the box shows one final transcript per
  utterance.
- Capability checklist: modes, "scratch that" and macros become ✅ once P6/P7
  land.
- Use `client_dir` (`default_config_dir()`) for the `floating_box_enabled`
  setting, alongside the other client data.
