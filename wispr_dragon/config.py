"""Configuration management for Wispr-Dragon."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


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
    silence_duration_ms: int = 500
    min_speech_duration_ms: int = 250
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
        if self.network_port <= 0 or self.network_port > 65535:
            raise ValueError(f"network_port must be in [1,65535], got {self.network_port}")


@dataclass
class EngineConfig:
    backend: str = "auto"  # "auto", "faster-whisper", "openai-whisper", "openai-api"
    model_size: str = "medium.en"
    device: str = "auto"  # "auto", "cuda", "cpu" (cuda works for both NVIDIA and AMD)
    compute_type: str = "auto"  # "auto", "float16", "int8", "float32" (ignored for openai-api)
    language: str = "en"
    beam_size: int = 5
    initial_prompt: str = ""
    hotwords: str = ""

    def __post_init__(self):
        valid_backends = {"auto", "faster-whisper", "openai-whisper", "openai-api"}
        if self.backend not in valid_backends:
            raise ValueError(f"backend must be one of {valid_backends}, got {self.backend}")
        valid_devices = {"auto", "cuda", "cpu"}
        if self.device not in valid_devices:
            raise ValueError(f"device must be one of {valid_devices}, got {self.device}")
        valid_compute = {"auto", "float16", "int8", "float32"}
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
class Config:
    audio: AudioConfig = field(default_factory=AudioConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    correction: CorrectionConfig = field(default_factory=CorrectionConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    user_dir: Path = DEFAULT_USER_DIR

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        path = path or DEFAULT_CONFIG_PATH
        if not path.exists():
            config = cls()
            config.save(path)
            return config

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        config = cls()
        if "audio" in data:
            config.audio = AudioConfig(**data["audio"])
        if "engine" in data:
            config.engine = EngineConfig(**data["engine"])
        if "correction" in data:
            config.correction = CorrectionConfig(**data["correction"])
        if "ui" in data:
            config.ui = UIConfig(**data["ui"])
        if "user_dir" in data:
            config.user_dir = Path(data["user_dir"])
        return config

    def save(self, path: Optional[Path] = None) -> None:
        path = path or DEFAULT_CONFIG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "audio": {
                "sample_rate": self.audio.sample_rate,
                "channels": self.audio.channels,
                "dtype": self.audio.dtype,
                "vad_threshold": self.audio.vad_threshold,
                "silence_duration_ms": self.audio.silence_duration_ms,
                "min_speech_duration_ms": self.audio.min_speech_duration_ms,
                "source": self.audio.source,
                "network_host": self.audio.network_host,
                "network_port": self.audio.network_port,
            },
            "engine": {
                "backend": self.engine.backend,
                "model_size": self.engine.model_size,
                "device": self.engine.device,
                "compute_type": self.engine.compute_type,
                "language": self.engine.language,
                "beam_size": self.engine.beam_size,
                "initial_prompt": self.engine.initial_prompt,
                "hotwords": self.engine.hotwords,
            },
            "correction": {
                "auto_apply_threshold": self.correction.auto_apply_threshold,
                "fuzzy_match_score": self.correction.fuzzy_match_score,
                "max_hotwords": self.correction.max_hotwords,
                "save_audio_segments": self.correction.save_audio_segments,
            },
            "ui": {
                "backend": self.ui.backend,
                "correction_shortcut": self.ui.correction_shortcut,
                "overlay_enabled": self.ui.overlay_enabled,
                "theme": self.ui.theme,
            },
            "user_dir": str(self.user_dir),
        }
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
