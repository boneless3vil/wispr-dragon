"""Configuration management for Wispr-Dragon."""

import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


# New default path uses underscore
DEFAULT_USER_DIR = Path.home() / ".wispr_dragon"
# Fallback to old path for backward compatibility
OLD_USER_DIR = Path.home() / ".wispr-dragon"

# Use old path if it exists and new one doesn't
if not DEFAULT_USER_DIR.exists() and OLD_USER_DIR.exists():
    DEFAULT_USER_DIR = OLD_USER_DIR

DEFAULT_CONFIG_PATH = DEFAULT_USER_DIR / "config.yaml"
DEFAULT_DICTIONARY_PATH = DEFAULT_USER_DIR / "user_dictionary.json"
DEFAULT_COMMANDS_PATH = DEFAULT_USER_DIR / "commands.yaml"
DEFAULT_LOG_DIR = DEFAULT_USER_DIR / "logs"


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    channels: int = 1
    dtype: str = "int16"
    vad_threshold: float = 0.5
    # How much trailing silence closes a speech segment. Each segment is
    # transcribed independently, so a short value shreds one sentence into
    # fragments ("a result." / "is due to.") and robs Whisper of the context it
    # needs — accuracy drops sharply below ~5 s of audio. 900 ms rides over the
    # natural pauses inside a sentence while still ending an utterance promptly.
    silence_duration_ms: int = 900
    min_speech_duration_ms: int = 250
    # Safety valve for utterance mode: force-finalize a held hotkey after this
    # long. Kept under Whisper's 30 s window so a single transcribe call never
    # hits faster-whisper's internal long-audio chunking (where accuracy drops),
    # and so a stuck hotkey can't grow the server buffer without bound.
    max_utterance_seconds: int = 25
    source: str = "pulseaudio"  # "pulseaudio" or "network"
    network_host: str = "0.0.0.0"
    network_port: int = 9876

    def __post_init__(self):
        if not 0 <= self.vad_threshold <= 1:
            raise ValueError(f"vad_threshold must be in [0,1], got {self.vad_threshold}")
        if self.sample_rate <= 0:
            raise ValueError(f"sample_rate must be > 0, got {self.sample_rate}")
        if self.channels <= 0:
            raise ValueError(f"channels must be > 0, got {self.channels}")
        if self.silence_duration_ms < 0:
            raise ValueError(f"silence_duration_ms must be >= 0, got {self.silence_duration_ms}")
        if self.min_speech_duration_ms < 0:
            raise ValueError(f"min_speech_duration_ms must be >= 0, got {self.min_speech_duration_ms}")
        if self.max_utterance_seconds <= 0:
            raise ValueError(
                f"max_utterance_seconds must be > 0, got {self.max_utterance_seconds}"
            )
        if self.network_port <= 0 or self.network_port > 65535:
            raise ValueError(f"network_port must be in [1,65535], got {self.network_port}")


@dataclass
class EngineConfig:
    backend: str = "auto"  # "auto", "faster-whisper", "openai-whisper", "openai-api"
    model_size: str = "small.en"
    device: str = "auto"  # "auto", "cuda", "cpu" (cuda works for both NVIDIA and AMD)
    compute_type: str = "auto"  # "auto", "float16", "int8", "int8_float16", "bfloat16", "float32"
    language: str = "en"
    beam_size: int = 10
    initial_prompt: str = ""
    hotwords: str = ""

    def __post_init__(self):
        valid_backends = {"auto", "faster-whisper", "openai-whisper", "openai-api"}
        if self.backend not in valid_backends:
            raise ValueError(f"backend must be one of {valid_backends}, got {self.backend}")
        valid_devices = {"auto", "cuda", "cpu"}
        if self.device not in valid_devices:
            raise ValueError(f"device must be one of {valid_devices}, got {self.device}")
        valid_compute = {"auto", "float16", "int8", "int8_float16", "bfloat16", "float32"}
        if self.compute_type not in valid_compute:
            raise ValueError(f"compute_type must be one of {valid_compute}, got {self.compute_type}")
        if self.beam_size < 1:
            raise ValueError(f"beam_size must be >= 1, got {self.beam_size}")


@dataclass
class CorrectionConfig:
    auto_apply_threshold: int = 3
    fuzzy_match_score: int = 85
    max_hotwords: int = 100
    save_audio_segments: bool = False

    def __post_init__(self):
        if not 0 <= self.fuzzy_match_score <= 100:
            raise ValueError(f"fuzzy_match_score must be in [0,100], got {self.fuzzy_match_score}")
        if self.auto_apply_threshold < 0:
            raise ValueError(f"auto_apply_threshold must be >= 0, got {self.auto_apply_threshold}")
        if self.max_hotwords < 0:
            raise ValueError(f"max_hotwords must be >= 0, got {self.max_hotwords}")


@dataclass
class UIConfig:
    backend: str = "auto"  # "auto", "pyqt6", "web"
    correction_shortcut: str = "ctrl+shift+c"
    overlay_enabled: bool = False
    theme: str = "system"


@dataclass
class SecurityConfig:
    allow_python_scripts: bool = True
    allow_yaml_macros: bool = True
    allow_program_launch: bool = True
    dictation_only: bool = False


@dataclass
class ServerConfig:
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8765
    api_key: str = ""
    tls_cert: str = ""
    tls_key: str = ""
    max_connections: int = 1

    def __post_init__(self):
        if self.port <= 0 or self.port > 65535:
            raise ValueError(f"port must be in [1,65535], got {self.port}")
        if self.max_connections < 1:
            raise ValueError(f"max_connections must be >= 1, got {self.max_connections}")


@dataclass
class Config:
    audio: AudioConfig = field(default_factory=AudioConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    correction: CorrectionConfig = field(default_factory=CorrectionConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    user_dir: Path = DEFAULT_USER_DIR

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        path = path or DEFAULT_CONFIG_PATH
        if not path.exists():
            config = cls()
            config.save(path)
            return config

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected a mapping at the top level")

        config = cls()
        for name, section_cls in _SECTIONS.items():
            if name in data:
                setattr(config, name, section_cls(**_section_kwargs(section_cls, data[name], name)))
        if data.get("user_dir"):
            config.user_dir = Path(data["user_dir"])
        # Later saves go back to the file this came from, not the default path.
        config._path = path
        _warn_if_key_exposed(path, config)
        return config

    def save(self, path: Optional[Path] = None) -> None:
        path = path or getattr(self, "_path", None) or DEFAULT_CONFIG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {name: asdict(getattr(self, name)) for name in _SECTIONS}
        data["user_dir"] = str(self.user_dir)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        path.chmod(0o600)
        # Remember it (covers first run, where load() creates the file).
        self._path = path


_SECTIONS = {
    "audio": AudioConfig,
    "engine": EngineConfig,
    "correction": CorrectionConfig,
    "ui": UIConfig,
    "security": SecurityConfig,
    "server": ServerConfig,
}


def _section_kwargs(section_cls, raw, name: str) -> dict:
    """Keyword args for one config section, tolerating old or partial files.

    An empty section (``audio:``) means defaults; keys this version doesn't
    know (renamed or retired settings) are dropped with a warning instead of
    crashing startup.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"config section '{name}' must be a mapping, got {type(raw).__name__}")
    known = {f.name for f in fields(section_cls)}
    unknown = sorted(set(raw) - known)
    if unknown:
        logger.warning("Ignoring unknown config key(s) in '%s': %s", name, ", ".join(unknown))
    return {k: v for k, v in raw.items() if k in known}


def _warn_if_key_exposed(path: Path, config: "Config") -> None:
    """The server API key is a credential; flag a config others can read."""
    if os.name != "posix" or not config.server.api_key:
        return
    try:
        if path.stat().st_mode & 0o077:
            logger.warning(
                "%s holds the server api_key but is readable by other users — "
                "run: chmod 600 %s", path, path,
            )
    except OSError:
        pass
