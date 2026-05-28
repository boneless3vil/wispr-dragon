# Wispr Dragon - Architecture Design Document
**Version**: 2.0 (Client-Server Architecture)  
**Status**: Design Phase  
**Date**: May 12, 2026

---

## Table of Contents
1. [Executive Summary](#executive-summary)
2. [Project Naming](#project-naming)
3. [Architecture Overview](#architecture-overview)
4. [Component Breakdown](#component-breakdown)
5. [Communication Protocol](#communication-protocol)
6. [Data Flow](#data-flow)
7. [Database Schema](#database-schema)
8. [Security & Authentication](#security--authentication)
9. [Implementation Phases](#implementation-phases)
10. [Technology Stack](#technology-stack)
11. [Deployment Model](#deployment-model)

---

## Executive Summary

Wispr Dragon is evolving from a **monolithic desktop application** into a **distributed client-server architecture** that delivers Nuance Dragon 16.1-like features across multiple platforms (Windows, macOS, Linux) on a local home network.

### Core Vision
- **Server**: Central processing hub on local network. Handles all heavy computation (VAD, transcription, correction, learning).
- **Clients**: Lightweight listeners on any device. Capture audio, display results, inject text into focused window.
- **Performance**: Leverages home network speed + substantial hardware for real-time, accurate speech recognition.
- **Usability**: Single unified correction dictionary learned across all devices. Multi-device session support.

### Key Requirements Met
✅ Run from server (local home network)  
✅ Call from main computer (any device on network)  
✅ Server does all processing  
✅ Cross-platform support (Windows, Mac, Linux)  
✅ Cursor-focused text injection  
✅ Real-time performance (network optimized)  

---

## Project Naming

### Current Issue
"Wispr Dragon" is functional but lacks originality. Below are naming suggestions:

### Tier 1 - Recommended (Short, Catchy, Memorable)

| Name | Meaning | Appeal |
|------|---------|--------|
| **Aria** | Roman goddess of voice | Voice-centric, elegant, works in code |
| **Cadence** | Flow/rhythm of speech | Tech-friendly, metaphorical, distinctive |
| **Resonance** | Depth of sound/impact | Poetic, implies quality, open-source vibes |
| **Voicebridge** | Bridges voice input to text output | Descriptive but still memorable |
| **Vox** | Latin for voice | Short, elegant, professional |
| **Echo** | Reflects/repeats voice | Simple, clever, strong mental model |

### Tier 2 - Unique Variants
- **AirVox** (air + voice) - Implies wireless, distributed
- **Nexus** - Central hub connecting devices
- **Atlas** - Server carries the load, clients consume results
- **Conductor** - Orchestrates voice into action

### Recommendation
🎯 **Go with "Aria"** or **"Cadence"**
- Both are distinctive from "Dragon"
- Professional yet approachable
- Work well in marketing and technical docs
- Short domain names available

**For now**: Use **Cadence** as working name; revisit if you prefer Aria or another.

---

## Architecture Overview

### System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    LOCAL HOME NETWORK (192.168.x.x)         │
└─────────────────────────────────────────────────────────────┘
         │
         ├─────────────────────┬──────────────────┬──────────────┐
         │                     │                  │              │
    ┌────▼────┐          ┌────▼────┐       ┌────▼────┐   ┌───▼────┐
    │ Client 1 │          │ Client 2 │       │ Client 3 │   │ Server │
    │(Windows) │          │  (macOS) │       │ (Linux)  │   │        │
    └─┬──────┬─┘          └─┬──────┬─┘       └─┬───────┬┘   └────┬───┘
      │      │              │      │            │       │         │
      │      └──Audio────────│──────┼────────────┼───────┼─────────┤
      │                      │      │            │       │         │
      │      ┌──Commands─────┴──────┴────────────┴───────┴─────────┤
      │      │                                                      │
      │      │   ┌────────────────────────────────────────────┐    │
      │      │   │         WebSocket Gateway (8000)           │    │
      │      │   │ - Streaming audio upload                   │    │
      │      │   │ - Real-time transcription results          │    │
      │      │   │ - Command dispatch                         │    │
      │      │   │ - User session management                  │    │
      │      │   └────────────────────────────────────────────┘    │
      │      │                                                      │
      │      │   ┌────────────────────────────────────────────┐    │
      │      │   │      REST API (8001)                       │    │
      │      │   │ - User dictionary CRUD                     │    │
      │      │   │ - Configuration get/set                    │    │
      │      │   │ - Session history                          │    │
      │      │   │ - Statistics                               │    │
      │      │   └────────────────────────────────────────────┘    │
      │      │                                                      │
      │      └──────────────────────────────────────────────────────┤
      │                                                             │
      └─Text Output (xdotool)──────────────────────────────────────┘
         (Local window injection only)
```

### Component Responsibilities

#### **Server** (Central Processing)
Runs on powerful machine on home network. Handles all heavy computation.

**Core Services**:
1. **Audio Queue Manager** - Buffers streaming audio from clients
2. **VAD Service** - Voice Activity Detection (Silero VAD, ~600MB model)
3. **Transcription Service** - 3-backend transcription (faster-whisper primary)
4. **Correction Engine** - Exact + fuzzy matching against user dictionary
5. **Post-Processor** - Formatting, capitalization, phrase replacements
6. **User Dictionary Store** - PostgreSQL/SQLite persistent storage
7. **Mode Manager** - Session state (Dictation/Command/Sleep per user)
8. **Command Matcher** - Fuzzy command matching + hotword biasing
9. **WebSocket Gateway** - Real-time communication with clients
10. **REST API** - Configuration & persistent data access
11. **Authentication** - User management (local network)
12. **Logging & Analytics** - Transcription accuracy, performance metrics

#### **Client** (Lightweight UI)
Runs on any device (Windows, Mac, Linux). Minimal local processing.

**Core Functions**:
1. **Audio Capture** - sounddevice (local mic) + stream to server
2. **Network Manager** - WebSocket connection + reconnection logic
3. **Text Injector** - Insert transcribed text into active window (OS-dependent)
4. **UI Manager** - Correction window (PyQt6 or Electron/web)
5. **Local Cache** - Recent corrections for offline fallback
6. **Device Management** - Track active device/window focus
7. **Mode Indicator** - Visual feedback (Dictation/Command/Sleep mode)
8. **Settings Panel** - Client-specific config (audio device, hotkeys)

---

## Component Breakdown

### Server Architecture (Detailed)

```
wispr_dragon_server/
├── main.py                          # FastAPI + WebSocket entry point
├── config.py                        # Server config (YAML)
├── database/
│   ├── models.py                   # SQLAlchemy models
│   ├── crud.py                     # DB operations
│   └── init.py                     # Setup & migrations
├── services/
│   ├── audio_queue.py              # Audio buffer management
│   ├── vad_service.py              # Silero VAD async wrapper
│   ├── transcription_service.py    # Async transcription + fallback
│   ├── correction_engine.py        # (refactored from correction/)
│   ├── post_processor.py           # (refactored from correction/)
│   ├── mode_manager.py             # (refactored from modes/)
│   ├── command_matcher.py          # (refactored from modes/)
│   └── session_manager.py          # Per-user session state (NEW)
├── api/
│   ├── websocket_gateway.py        # WebSocket handlers for streaming audio + results
│   ├── rest_api.py                 # Dictionary, config, stats endpoints
│   └── auth.py                     # User authentication (NEW)
├── models/                          # (refactored from engine/)
│   ├── base.py
│   ├── faster_whisper_engine.py
│   ├── openai_whisper_engine.py
│   └── openai_api_engine.py
└── utils/
    ├── logging.py
    ├── metrics.py
    └── device_detection.py
```

### Client Architecture (Detailed)

```
wispr_dragon_client/
├── main.py                         # Entry point
├── config.py                       # Client config
├── network/
│   ├── websocket_client.py        # WebSocket streaming + reconnection
│   ├── rest_client.py             # REST API calls for config/dict
│   └── message_handlers.py        # Process server messages
├── audio/
│   ├── capture.py                 # sounddevice wrapper
│   └── device_manager.py          # Input device selection
├── output/
│   ├── text_injector.py           # (xdotool/Windows API/Cocoa)
│   └── platform_adapter.py        # OS-specific implementations
├── ui/
│   ├── main_window.py             # (PyQt6 or web-based)
│   ├── correction_dialog.py       # Correction window
│   ├── mode_indicator.py          # Visual mode display
│   └── settings_panel.py          # Client configuration
├── cache/
│   ├── local_cache.py             # Recent corrections + mode state
│   └── offline_store.py           # Fallback data if server down
└── utils/
    ├── audio_utils.py
    ├── logging.py
    └── platform_utils.py
```

---

## Communication Protocol

### WebSocket Gateway (Primary Channel)
**Endpoint**: `ws://server_ip:8000/ws/stream`

**Connection Flow**:
```
CLIENT                              SERVER
│                                   │
├─ Connect + Auth Token ────────────>
│                                   ├─ Validate user
│                                   ├─ Create session
│                                   ├─ Load user dictionary
│                                   │
│<─ Connection Accepted + Metadata ─┤
│  (engine version, VAD info)       │
│                                   │
├─ Audio Chunk (16kHz, int16) ─────>
├─ Audio Chunk ─────────────────────>
├─ Audio Chunk (+ END_OF_SPEECH) ──>
│                                   ├─ VAD processes chunks
│                                   ├─ Transcription runs
│                                   ├─ Correction applied
│                                   │
│<─ TranscriptionResult JSON ───────┤
│  {                                │
│    id: "seg_123",                 │
│    text: "Hello world",           │
│    confidence: 0.95,              │
│    mode_action: "output_text",    │
│    timestamp: "2026-05-12T..."    │
│  }                                │
│                                   │
├─ Audio Chunk ────────────────────>
│ ...                               │
```

**Message Format - Audio Upload**:
```json
{
  "type": "audio",
  "data": "<base64-encoded int16 PCM>",
  "sample_rate": 16000,
  "sequence": 42,
  "end_of_speech": false
}
```

**Message Format - Transcription Result**:
```json
{
  "type": "transcription_result",
  "segment_id": "seg_12345",
  "original_text": "correct taht",
  "corrected_text": "correct that",
  "confidence": 0.92,
  "engine_used": "faster-whisper",
  "mode": "dictation",
  "action": "output_text",
  "timestamp": "2026-05-12T14:32:45.123Z",
  "alternatives": [
    {"text": "correct that", "confidence": 0.92},
    {"text": "correct that's", "confidence": 0.88}
  ]
}
```

**Message Format - Command Action**:
```json
{
  "type": "command_result",
  "command": "select_all",
  "success": true,
  "message": "Command matched and executed"
}
```

### REST API (Secondary Channel)

**Base URL**: `http://server_ip:8001/api/v1`

**Endpoints**:

#### Dictionary Management
```
GET    /users/{user_id}/dictionary
  → Returns full user dictionary (JSON)

POST   /users/{user_id}/dictionary/corrections
  Body: {"wrong": "john ball win", "correct": "John Baldwin"}
  → Add correction to dictionary (instantly synced)

GET    /users/{user_id}/dictionary/search?text=john
  → Fuzzy search for corrections

POST   /users/{user_id}/dictionary/sync
  Body: {timestamp: "2026-05-12T14:32:00Z"}
  → Sync user dictionary with last-modified timestamp
```

#### Configuration
```
GET    /users/{user_id}/config
  → Get user's current config (audio threshold, engine, etc.)

PATCH  /users/{user_id}/config
  Body: {vad_threshold: 0.6, backend: "faster-whisper"}
  → Update configuration

GET    /config/servers
  → Get available transcription backends & their status
```

#### Session & Statistics
```
GET    /users/{user_id}/sessions
  → List recent sessions

GET    /users/{user_id}/sessions/{session_id}
  → Get detailed session transcripts

GET    /users/{user_id}/stats
  → Aggregated stats (total words, accuracy, commands used, etc.)

POST   /users/{user_id}/sessions/{session_id}/rate
  Body: {segment_id: "seg_123", rating: "good"}
  → Feedback for accuracy improvement
```

#### Server Status
```
GET    /health
  → Server status (VAD ready, GPU available, etc.)

GET    /models
  → Available transcription models & their status

GET    /devices
  → GPU devices & current load
```

---

## Data Flow

### Complete Speech Recognition Pipeline

```
CLIENT SIDE (Audio Capture)
├─ 1. User speaks into microphone
├─ 2. AudioCapture (sounddevice) streams 30ms chunks (480 samples @ 16kHz)
├─ 3. Chunks buffered locally (500ms buffer for smoothing)
├─ 4. Streamed to server via WebSocket (base64 encoded int16 PCM)
└─ 5. Wait for transcription result from server

SERVER SIDE (Processing)
├─ 6. WebSocket Gateway receives audio chunk
├─ 7. Audio Queue Manager stores in buffer
├─ 8. VAD Service (Silero) processes chunk
│   └─ Detects speech segments (confidence >= threshold)
├─ 9. When speech segment complete (silence > 500ms):
│   ├─ Extract segment from buffer
│   ├─ Pass to Transcription Service
│   └─ 10. Transcription (faster-whisper preferred, with hotwords)
│       └─ Returns: text, confidence, word-level timestamps
├─ 11. Correction Engine applies user dictionary
│   ├─ Exact match corrections (high frequency)
│   ├─ Fuzzy match corrections (80%+ similarity)
│   ├─ Phrase replacements
│   └─ Returns: corrected_text, applied_corrections
├─ 12. Mode Manager evaluates mode + text
│   ├─ Dictation mode: Post-processor (formatting, capitalization)
│   ├─ Command mode: Command Matcher (fuzzy match against grammar)
│   └─ Sleep mode: Ignore (unless "wake up")
├─ 13. Format response with:
│   ├─ Original transcription
│   ├─ Corrected text
│   ├─ Confidence score
│   ├─ Recommended action (output_text, execute_command, etc.)
│   └─ Timestamp & segment ID
└─ 14. Send result via WebSocket

CLIENT SIDE (Output)
├─ 15. Receive TranscriptionResult
├─ 16. Evaluate action:
│   ├─ If "output_text": TextInjector inserts into active window
│   ├─ If "command_result": Display feedback (optional visual)
│   ├─ If "open_correction": Show correction dialog
│   └─ If "no_output": Silently logged
├─ 17. Update local cache with result
├─ 18. If user corrects, send via REST API to update dictionary
└─ 19. Ready for next audio chunk
```

### Correction Learning Flow

```
CLIENT SIDE (User Correction)
├─ 1. User says "correct that"
├─ 2. Server opens correction dialog on client
├─ 3. User types correction
├─ 4. User clicks "Apply" or "Always Apply"
│
├─ 5. Client sends to server via REST POST /users/{id}/dictionary/corrections
│   └─ {wrong: "original", correct: "user_typed", frequency: N, always_apply: bool}
│
SERVER SIDE (Learning)
├─ 6. Correction Engine updates UserDictionary
│   ├─ Increment frequency counter
│   ├─ If frequency >= auto_apply_threshold (3): Mark for auto-apply
│   └─ Update last_modified timestamp
├─ 7. Persist to database
├─ 8. Update in-memory dictionary cache
├─ 9. Regenerate hotword list for transcription (top 100 by frequency)
│
ALL OTHER CLIENTS
├─ 10. If client config has "sync_dictionary: true"
├─ 11. Client periodically syncs via REST GET /users/{id}/dictionary/sync
│   └─ Only fetch corrections modified since last sync
├─ 12. Update local cache for offline fallback
└─ 13. All clients now use updated corrections automatically
```

---

## Database Schema

### Core Tables

**Users** (Authentication + Profiles)
```sql
CREATE TABLE users (
  id UUID PRIMARY KEY,
  username VARCHAR(255) UNIQUE,
  email VARCHAR(255) UNIQUE,
  password_hash VARCHAR(255),
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  is_active BOOLEAN DEFAULT true
);
```

**User Dictionaries** (Persistent Corrections)
```sql
CREATE TABLE user_dictionaries (
  id UUID PRIMARY KEY,
  user_id UUID FOREIGN KEY,
  wrong_text VARCHAR(500),
  correct_text VARCHAR(500),
  frequency INT DEFAULT 1,
  confidence FLOAT DEFAULT 0.5,  -- User-provided confidence
  last_used TIMESTAMP,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  auto_apply BOOLEAN DEFAULT false,
  alternatives JSON,  -- Array of alternative corrections
  UNIQUE(user_id, wrong_text)
);

CREATE INDEX idx_user_dict_user_id ON user_dictionaries(user_id);
CREATE INDEX idx_user_dict_frequency ON user_dictionaries(frequency DESC);
```

**User Configurations**
```sql
CREATE TABLE user_configs (
  id UUID PRIMARY KEY,
  user_id UUID FOREIGN KEY UNIQUE,
  vad_threshold FLOAT DEFAULT 0.5,
  silence_duration_ms INT DEFAULT 500,
  min_speech_duration_ms INT DEFAULT 250,
  backend VARCHAR(50) DEFAULT "faster-whisper",
  model_size VARCHAR(50) DEFAULT "medium.en",
  device VARCHAR(50) DEFAULT "auto",
  language VARCHAR(10) DEFAULT "en",
  beam_size INT DEFAULT 5,
  auto_capitalize BOOLEAN DEFAULT true,
  sync_dictionary BOOLEAN DEFAULT true,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);
```

**Sessions** (User Activity Log)
```sql
CREATE TABLE sessions (
  id UUID PRIMARY KEY,
  user_id UUID FOREIGN KEY,
  device_name VARCHAR(255),
  client_version VARCHAR(50),
  mode VARCHAR(50) DEFAULT "dictation",
  started_at TIMESTAMP,
  ended_at TIMESTAMP,
  segment_count INT DEFAULT 0,
  accuracy FLOAT,  -- Computed as avg confidence
  notes TEXT
);

CREATE INDEX idx_session_user_id ON sessions(user_id);
CREATE INDEX idx_session_started_at ON sessions(started_at DESC);
```

**Transcription Segments** (Fine-grained History)
```sql
CREATE TABLE transcription_segments (
  id UUID PRIMARY KEY,
  session_id UUID FOREIGN KEY,
  user_id UUID FOREIGN KEY,
  original_audio_hash VARCHAR(64),  -- SHA256 of audio
  original_text VARCHAR(2000),
  corrected_text VARCHAR(2000),
  confidence FLOAT,
  engine_used VARCHAR(50),
  processing_time_ms INT,
  word_count INT,
  user_rating VARCHAR(20),  -- "good", "bad", "needs_review"
  timestamp TIMESTAMP,
  created_at TIMESTAMP
);

CREATE INDEX idx_segment_session_id ON transcription_segments(session_id);
CREATE INDEX idx_segment_user_id ON transcription_segments(user_id);
CREATE INDEX idx_segment_timestamp ON transcription_segments(timestamp DESC);
```

**Commands** (User-defined Voice Commands)
```sql
CREATE TABLE custom_commands (
  id UUID PRIMARY KEY,
  user_id UUID FOREIGN KEY,
  command_text VARCHAR(500),
  action_type VARCHAR(100),  -- "keystroke", "text", "execute", etc.
  action_payload JSON,  -- {keystroke: "ctrl+s"} or {text: "Hello"}
  description VARCHAR(500),
  enabled BOOLEAN DEFAULT true,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);

CREATE INDEX idx_command_user_id ON custom_commands(user_id);
```

**Hotwords** (Dynamic Biasing - Cache)
```sql
CREATE TABLE hotword_cache (
  id UUID PRIMARY KEY,
  user_id UUID FOREIGN KEY UNIQUE,
  hotword_list TEXT,  -- Comma-separated, top 100 by frequency
  session_words JSON,  -- Recently discovered words this session
  last_updated TIMESTAMP
);
```

---

## Security & Authentication

### Authentication Mechanism

**For Local Network Only** (No external exposure):

1. **Initial Setup**:
   - Server generates random 32-char API token on first run
   - User saves token in client config file (plaintext, local only)
   - Optional: User can set password in client UI (hashed server-side)

2. **Connection Flow**:
   ```
   Client: Connect to ws://server_ip:8000/ws/stream?token=ABC123...
   Server: Validate token + validate user exists
   Client: Authenticated ✓
   ```

3. **REST API**:
   ```
   Authorization: Bearer <token>
   X-Client-Version: 2.0.0
   X-Device-Name: Jonathan-MacBook
   ```

### Data Security

| Data | Sensitivity | Protection |
|------|-------------|-----------|
| Audio streams | High | Encrypted in transit (WSS), not stored (deleted after transcription) |
| Transcripts | High | Stored locally on user's network only |
| User dictionary | Medium | Encrypted at rest (AES-256 in DB), synced over HTTPS |
| Config | Low | Plaintext in DB, available only via authenticated API |
| Auth tokens | Critical | Server-side hashing, rotation recommended quarterly |

### Recommended Additions (Future)
- [ ] HTTPS/WSS (self-signed cert for local network)
- [ ] Multi-user with separate dictionaries
- [ ] Audit logging (who edited what dictionary entry)
- [ ] Rate limiting per user (prevent dictionary spam)
- [ ] Backup/restore of dictionary

---

## Implementation Phases

### Phase 1: Server Foundation (Weeks 1-2)
**Goal**: Basic server infrastructure + refactored engines

- [ ] Create `wispr_dragon_server` package
- [ ] Set up FastAPI + WebSocket gateway (listening on 8000)
- [ ] Refactor transcription engines (move from desktop monolith)
  - Copy engine/ folder → server/models/
  - Add async wrapper for transcription
  - Add engine pooling for parallel processing
- [ ] Refactor correction engine (move dictionary.py, post_processor.py)
  - Load from SQLite initially (upgrade to PostgreSQL later)
  - Add async dictionary lookups
- [ ] Set up basic REST API skeleton (config/dictionary endpoints)
- [ ] Docker configuration for server deployment

**Deliverables**:
- Server accepts WebSocket connections
- Server can receive and process audio chunks
- Transcription returns results back to client
- No authentication yet (localhost only)

### Phase 2: Client Refactoring (Weeks 2-3)
**Goal**: Lightweight client that communicates with server

- [ ] Create `wispr_dragon_client` package
- [ ] Refactor AudioCapture → remove VAD (keep only capture)
- [ ] Create WebSocket client
  - Connect to server
  - Stream audio chunks
  - Receive and handle transcription results
- [ ] Refactor TextInjector (extract OS-specific code)
  - Create platform_adapter.py for Windows/Mac/Linux
  - Handle xdotool (Linux), applescript (Mac), pyautogui (Windows)
- [ ] Migrate PyQt6 UI to client
- [ ] Implement local caching (offline fallback)

**Deliverables**:
- Client connects to server
- Client captures audio + sends to server
- Client receives transcription + injects into active window
- Client UI shows mode indicator

### Phase 3: Dictionary & Persistence (Week 3-4)
**Goal**: Shared user dictionary + session tracking

- [ ] Create database schema (SQLite → PostgreSQL)
- [ ] Migrate existing user_dictionary.json → DB
- [ ] REST API endpoints:
  - POST /users/{id}/dictionary/corrections
  - GET /users/{id}/dictionary
  - PATCH /users/{id}/config
- [ ] Client-side sync logic
  - Periodic fetch of updated dictionary
  - Conflict resolution (server wins)
- [ ] Session tracking
  - Start session on client connect
  - End session on disconnect
  - Log transcription segments

**Deliverables**:
- Corrections made on one client sync to all clients
- User dictionary persists across sessions
- Session history available via API

### Phase 4: Mode Manager & Commands (Week 4)
**Goal**: Stateful session management + command execution

- [ ] Refactor mode_manager.py → server-side
  - Track per-user session mode (Dictation/Command/Sleep)
  - Mode switching commands work globally
- [ ] Refactor command_mode.py → server-side
  - Load default + user commands from database
  - Fuzzy matching with placeholders
  - Return matched command to client
- [ ] Client-side mode indicator
  - Visual feedback (icon, tray color, etc.)
- [ ] Command execution framework
  - "select all" → sends action to client
  - Client executes via TextInjector or direct API

**Deliverables**:
- Users can switch modes via voice
- Commands are matched + actions sent to client
- Mode state persists across reconnects

### Phase 5: Authentication & Multi-User (Week 5)
**Goal**: Secure multi-user support

- [ ] User table schema + auth endpoints
  - POST /auth/register
  - POST /auth/login
  - POST /auth/logout
- [ ] Token-based authentication (JWT or simple tokens)
- [ ] Client login UI (username/password or token paste)
- [ ] Dictionary isolation per user
- [ ] Session per user (no dictionary/correction sharing)

**Deliverables**:
- Multiple users can use same server
- Each user has separate dictionary
- Server restricts dictionary access via user_id

### Phase 6: Advanced Features (Week 6+)
**Goal**: Nuance Dragon feature parity

- [ ] Hotword biasing (top 100 words from dictionary)
- [ ] Real-time feedback (visual display of confidence)
- [ ] Accuracy metrics dashboard
- [ ] Command history + repeatable commands
- [ ] Multi-language support
- [ ] Custom vocabulary profiles (legal, medical, technical)
- [ ] Audio preprocessing (noise suppression, echo cancellation)
- [ ] Partial transcription (show-as-you-speak)

**Nice-to-Haves**:
- [ ] Web dashboard (view sessions, edit dictionary, stats)
- [ ] Mobile companion app (control from phone)
- [ ] Voice macro recording (repeat complex command sequences)
- [ ] Integration with calendar/email (voice-aware context)

---

## Technology Stack

### Server

| Layer | Technology | Rationale |
|-------|----------|-----------|
| **Framework** | FastAPI + uvicorn | Async, WebSocket support, built-in OpenAPI docs |
| **WebSocket** | websockets (Python) | Pure async, low-latency streaming |
| **Database** | PostgreSQL (or SQLite for dev) | ACID compliance, JSON support for alternatives, scalable |
| **ORM** | SQLAlchemy | Flexible, supports multiple databases |
| **Async** | asyncio + aiofiles | Python native, integrates with FastAPI |
| **Audio Processing** | librosa, scipy | Standard DSP tools |
| **Transcription** | faster-whisper (CTranslate2), openai-whisper, openai-api | Existing integrations |
| **Deployment** | Docker + Docker Compose | Consistent across machines |
| **Monitoring** | Prometheus + Grafana (future) | Track server health |

### Client

| Layer | Technology | Rationale |
|-------|----------|-----------|
| **Framework** | PyQt6 (or Electron for web) | Desktop-ready, cross-platform |
| **Audio Capture** | sounddevice | Low-latency, cross-platform |
| **Network** | websockets (Python) + requests | Standard async+REST |
| **Text Injection** | xdotool (Linux), PyAutoGUI (Windows), PyObjC (Mac) | Direct window/system access |
| **Config** | YAML (local file) | Human-readable, simple |
| **Packaging** | PyInstaller (Python) or Electron (web) | Single executable |
| **Logging** | loguru | Rich, colorized output |

### Shared

| Component | Technology |
|-----------|-----------|
| **Protocol** | WebSocket (binary + JSON) + REST (JSON) |
| **Serialization** | JSON (fast), MessagePack (future for binary efficiency) |
| **Secrets** | Python decouple or .env file (dev) |
| **Testing** | pytest + pytest-asyncio |
| **CI/CD** | GitHub Actions (linting, tests, builds) |

---

## Deployment Model

### Development

```
Developer Machine
├─ Server (localhost:8000 + 8001)
├─ Client (localhost)
└─ PostgreSQL (localhost:5432)
```

**Start**:
```bash
# Terminal 1: Server
docker-compose up postgres redis
poetry run python -m wispr_dragon_server

# Terminal 2: Client
poetry run python -m wispr_dragon_client
```

### Home Network Deployment

```
Server Machine (Ubuntu on WSL or bare metal)
├─ FastAPI server (192.168.1.100:8000 + 8001)
├─ PostgreSQL database (192.168.1.100:5432)
└─ GPU hardware (CUDA/ROCm for faster-whisper)

Client Machines (Windows, Mac, Linux)
├─ Lightweight client (no GPU required)
└─ Microphone + speaker
```

**Setup**:
1. Server: Run Docker container or systemd service
2. Client: Download client executable, configure server IP + token
3. Both: Share network (no external internet required)

**Networking**:
- Server IP: Static (set in router DHCP or manual)
- Client: Discovers server IP via:
  - Manual entry in settings
  - mDNS (server advertises itself as `cadence.local`)
  - Manual IP list in config file

### Cloud Deployment (Optional Future)

For remote use (outside home network):
- Deploy server to cloud VPS (AWS, DigitalOcean, etc.)
- Replace local token auth with proper HTTPS + TLS
- Add rate limiting + bot detection
- Larger database (PostgreSQL on RDS)

---

## Next Steps

### Immediate Actions
1. **Decide on project name** → Update README + all references
2. **Set up development environment**:
   ```bash
   git checkout -b dev/client-server-refactor
   mkdir wispr_dragon_server wispr_dragon_client
   ```
3. **Create project structure** (folder layout, __init__.py files)
4. **Set up Docker** (postgres, dev server)
5. **Begin Phase 1** (FastAPI + WebSocket skeleton)

### Questions to Clarify
- [ ] Database choice: PostgreSQL now or SQLite for now?
- [ ] Client UI: Keep PyQt6 or migrate to Electron/web?
- [ ] Deployment: Docker containers or native systemd services?
- [ ] Multi-user: Support from day 1 or Phase 5 only?
- [ ] GPU sharing: Can multiple clients share one GPU, or separate queues?

### Risk Mitigation
| Risk | Mitigation |
|------|-----------|
| Network latency | Keep audio chunks small (30ms), use binary protocol (MessagePack) |
| Server overload | Implement job queue (Celery) + rate limiting |
| Client reconnection | Automatic reconnect with backoff, local cache for offline |
| Audio sync drift | Include timestamps in all messages, server orchestrates timing |
| Dictionary conflicts | Server-of-truth design, REST endpoints for atomic updates |

---

## Document Metadata
- **Author**: GitHub Copilot
- **Status**: Design Phase (Ready for Implementation)
- **Last Updated**: May 12, 2026
- **Next Review**: After Phase 1 completion
