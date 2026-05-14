# Wispr-Dragon Upgrade Roadmap

Future features and enhancements planned for post-v1.0 releases.

---

## v1.1: AI-Powered Script Generation

### Context
Users can voice a complex task, and Wispr Dragon will automatically generate the appropriate script/command and execute it.

### Workflow

```
[Voice Input]
    ↓
[Speech Recognition]
    ↓
[Text Analysis]
    ↓
[Determine Type: Shell/PowerShell/Python/YAML]
    ↓
[Pipe to Coding Model (Claude API)]
    ↓
[Model Generates Script/Command]
    ↓
[Execute Generated Script]
    ↓
[Pipe Output Back to User]
```

### Examples

**Voice:** "Create a Python script that fetches weather from OpenWeather API"
- Wispr recognizes this as a software task
- Pipes request to Claude API with prompt: "Generate Python script for fetching OpenWeather API data"
- Claude generates the script
- Script is auto-signed and stored
- Script executes, output injected as text

**Voice:** "PowerShell: List all installed applications"
- Wispr recognizes PowerShell command
- Pipes to Claude: "Generate PowerShell script to list installed applications"
- Claude generates the command
- Executes in PowerShell
- Output displayed/injected

**Voice:** "YAML: Create a deployment macro for Docker containers"
- Wispr recognizes YAML/macro intent
- Pipes to Claude: "Generate YAML macro for Docker deployment"
- Claude generates macro file
- Macro is added to macros/ directory
- User can immediately voice-trigger it

### Implementation Details

**New module:** `wispr_dragon/ai_scripting/`
- `code_generator.py` — Interface to Claude API (with prompt caching for performance)
- `intent_detector.py` — Determine if transcribed text is a code/script request
- `script_executor.py` — Execute generated scripts safely
- `output_handler.py` — Return results to user (text injection, display, etc)

**Config additions:**
```yaml
ai_scripting:
  enabled: true
  model: "claude-opus-4-7"  # Latest Claude model
  temperature: 0.3          # Low randomness for code generation
  max_tokens: 2048
  cache_prompts: true       # Use prompt caching for faster API calls
```

**CLI commands:**
- `wispr_dragon --enable-ai-scripting` — Turn on AI script generation
- `wispr_dragon --ai-script-history` — View recently generated scripts
- `wispr_dragon --review-generated <script>` — Show and approve before execution

**Safety considerations:**
- All AI-generated scripts must be reviewed before execution (confirmation dialog)
- Generated scripts are sandboxed (timeout, resource limits)
- Dangerous operations (rm -rf, format disk, etc) are detected and blocked
- User approval required for scripts with file system/network access
- Generated scripts are logged for audit trail

**Performance optimization:**
- Use Claude API prompt caching to avoid re-sending system prompts
- Cache common task templates (e.g., "list files", "check disk usage")
- Queue requests if multiple simultaneous generations

### Benefits
- Instant script generation without manual coding
- Natural language interface for automation
- Reduces need to memorize shell syntax
- Accessible to non-programmers

### Risks & Mitigations
| Risk | Mitigation |
|------|-----------|
| Generated code could be unsafe | Always show code before execution; use sandboxing |
| API rate limits / costs | Implement caching; allow offline mode with fallback |
| Model hallucination (bad code) | Require user approval; log failures for debugging |
| Privacy (sending transcripts to API) | Hash sensitive data; allow local-only mode |

---

## v1.2: Real-Time Confidence & Correction UI

### Transcription Confidence Display
- Show live confidence score for each recognized word
- Highlight low-confidence words for quick correction
- Allow in-place word replacement without re-dictating

### Interactive Correction Panel
- Real-time suggestion list as user speaks
- Click-to-replace workflow
- Learn user corrections (auto-add to dictionary)

---

## v1.3: Multi-Modal Input

### Gesture Recognition
- Hand gestures trigger commands (if webcam available)
- Voice + gesture for complex actions

### Keyboard Shortcuts
- F12 (or customizable key) to toggle dictation
- Chord bindings for quick command triggers

---

## v1.4: Cloud Sync & Collaboration

### Dictionary & Macros Sync
- Backup user dictionary to cloud (OneDrive, Google Drive, S3)
- Sync macros across devices
- Share macro packs with team members

### Community Macro Repository
- Public registry of user-created macros
- One-click macro import
- Ratings and reviews

---

## v2.0: Full UI with Dashboard

### System Tray Icon
- Mode indicator (Dictation / Command / Paused)
- Quick-access menu

### Settings Dashboard
- Web-based or PyQt6 GUI for all config options
- Macro editor with syntax highlighting
- Security policy visual editor

### Real-Time Transcription Overlay
- Floating window showing live transcription
- Confidence bars for each segment
- Alternative suggestions dropdown

### Performance Metrics
- Real-time Latency / Throughput display
- Engine performance comparison
- Audio quality indicator

---

## v2.1: Advanced Scripting

### Macro Workflows
- Conditional execution (if/else in YAML)
- Loops and repeats
- Variable binding between steps

### Script Templates
- Pre-built templates for common tasks
- Parameterized templates (fill in the blanks)

### Error Handling
- Macro rollback on failure
- Fallback actions
- User notifications

---

## v3.0: Enterprise Features

### Audit & Compliance
- Full script execution audit trail
- User activity logging
- Compliance reports (HIPAA, SOX, etc)

### RBAC (Role-Based Access Control)
- Admin vs. user vs. guest accounts
- Per-user macro restrictions
- Approval workflows for sensitive operations

### Integration Connectors
- Slack integration (trigger macros from Slack, post results)
- Jira/Linear integration
- Webhook support

---

## Technical Debt & Refactoring

### Phase 1 (Soon)
- [ ] Refactor `command_mode.py` global state → `CommandRegistry` class
- [ ] Consolidate path handling (remove legacy `~/.wispr-dragon` fallback)
- [ ] Standardize logging (replace remaining `print()` calls)
- [ ] Add comprehensive test coverage (target: 80%)

### Phase 2 (Post-v1)
- [ ] Migrate to async/await for I/O-bound operations
- [ ] Implement plugin system for third-party engines
- [ ] Performance profiling and optimization
- [ ] Refactor TextInjector to support more platforms (wayland, X11, clipboard)

---

## Known Limitations

1. **Audio Input** — Currently PulseAudio/network only; no native ALSA support
2. **Platform Support** — Linux/WSL2; macOS/Windows would require port
3. **Real-time Latency** — Faster-Whisper is fast but still ~1-2s per utterance
4. **Model Size** — Large models (large-v3) require GPU or significant CPU time
5. **Dictionary Learning** — Current fuzzy matching is basic; no ML-based learning

---

## Release Schedule (Estimated)

| Version | Target Date | Key Features |
|---------|-------------|--------------|
| v1.0 | May 2026 | Macros, Python scripts, 3-layer security |
| v1.1 | Jul 2026 | AI script generation, intent detection |
| v1.2 | Sep 2026 | Confidence UI, real-time correction |
| v1.3 | Nov 2026 | Gestures, keyboard shortcuts |
| v1.4 | Q1 2027 | Cloud sync, community macros |
| v2.0 | Q2 2027 | Full dashboard, tray icon, overlay |
| v3.0 | Q4 2027 | Enterprise RBAC, audit trail |

---

## Contributing

Community contributions welcome! Priority areas:
- Macro templates and examples
- Bug reports and fixes
- Documentation improvements
- Platform ports (macOS, native Windows)
- Engine implementations (other speech-to-text APIs)

See CONTRIBUTING.md for guidelines.
