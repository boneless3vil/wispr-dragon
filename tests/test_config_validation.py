"""Tests for configuration validation."""

from pathlib import Path
import tempfile

import pytest

from wispr_dragon.config import (
    AudioConfig, EngineConfig, CorrectionConfig, UIConfig, SecurityConfig, Config
)


class TestAudioConfig:
    """Tests for AudioConfig validation."""

    def test_valid_audio_config(self):
        """Test creating valid audio config."""
        config = AudioConfig(
            sample_rate=16000,
            vad_threshold=0.5,
            channels=1,
            silence_duration_ms=500,
            min_speech_duration_ms=250,
        )
        assert config.sample_rate == 16000

    def test_audio_config_vad_threshold_too_low(self):
        """Test that vad_threshold < 0 raises ValueError."""
        with pytest.raises(ValueError):
            AudioConfig(vad_threshold=-0.1)

    def test_audio_config_vad_threshold_too_high(self):
        """Test that vad_threshold > 1 raises ValueError."""
        with pytest.raises(ValueError):
            AudioConfig(vad_threshold=1.5)

    def test_audio_config_vad_threshold_zero_valid(self):
        """Test that vad_threshold=0 is valid."""
        config = AudioConfig(vad_threshold=0.0)
        assert config.vad_threshold == 0.0

    def test_audio_config_vad_threshold_one_valid(self):
        """Test that vad_threshold=1 is valid."""
        config = AudioConfig(vad_threshold=1.0)
        assert config.vad_threshold == 1.0

    def test_audio_config_sample_rate_zero(self):
        """Test that sample_rate=0 raises ValueError."""
        with pytest.raises(ValueError):
            AudioConfig(sample_rate=0)

    def test_audio_config_sample_rate_negative(self):
        """Test that negative sample_rate raises ValueError."""
        with pytest.raises(ValueError):
            AudioConfig(sample_rate=-16000)

    def test_audio_config_channels_zero(self):
        """Test that channels=0 raises ValueError."""
        with pytest.raises(ValueError):
            AudioConfig(channels=0)

    def test_audio_config_silence_duration_negative(self):
        """Test that negative silence_duration_ms raises ValueError."""
        with pytest.raises(ValueError):
            AudioConfig(silence_duration_ms=-1)

    def test_audio_config_min_speech_duration_negative(self):
        """Test that negative min_speech_duration_ms raises ValueError."""
        with pytest.raises(ValueError):
            AudioConfig(min_speech_duration_ms=-100)

    def test_audio_config_network_port_zero(self):
        """Test that network_port=0 raises ValueError."""
        with pytest.raises(ValueError):
            AudioConfig(network_port=0)

    def test_audio_config_network_port_too_high(self):
        """Test that network_port > 65535 raises ValueError."""
        with pytest.raises(ValueError):
            AudioConfig(network_port=70000)

    def test_audio_config_network_port_valid_range(self):
        """Test valid network port values."""
        config1 = AudioConfig(network_port=1)
        config2 = AudioConfig(network_port=65535)
        assert config1.network_port == 1
        assert config2.network_port == 65535


class TestEngineConfig:
    """Tests for EngineConfig validation."""

    def test_valid_engine_config(self):
        """Test creating valid engine config."""
        config = EngineConfig(
            backend="faster-whisper",
            model_size="base",
            beam_size=5,
        )
        assert config.backend == "faster-whisper"

    def test_engine_config_beam_size_zero(self):
        """Test that beam_size=0 raises ValueError."""
        with pytest.raises(ValueError):
            EngineConfig(beam_size=0)

    def test_engine_config_beam_size_negative(self):
        """Test that negative beam_size raises ValueError."""
        with pytest.raises(ValueError):
            EngineConfig(beam_size=-1)

    def test_engine_config_beam_size_one_valid(self):
        """Test that beam_size=1 is valid."""
        config = EngineConfig(beam_size=1)
        assert config.beam_size == 1

    def test_engine_config_valid_backends(self):
        """Test that all valid backends are accepted."""
        backends = ["auto", "faster-whisper", "openai-whisper", "openai-api"]
        for backend in backends:
            config = EngineConfig(backend=backend)
            assert config.backend == backend

    def test_engine_config_invalid_backend(self):
        """Test that invalid backend raises ValueError."""
        with pytest.raises(ValueError):
            EngineConfig(backend="invalid-engine")

    def test_engine_config_valid_devices(self):
        """Test that valid devices are accepted."""
        for device in ["auto", "cuda", "cpu"]:
            config = EngineConfig(device=device)
            assert config.device == device

    def test_engine_config_invalid_device(self):
        """Test that invalid device raises ValueError."""
        with pytest.raises(ValueError):
            EngineConfig(device="gpu")

    def test_engine_config_valid_compute_types(self):
        """Test that valid compute types are accepted."""
        for compute_type in ["auto", "float16", "int8", "float32"]:
            config = EngineConfig(compute_type=compute_type)
            assert config.compute_type == compute_type

    def test_engine_config_invalid_compute_type(self):
        """Test that invalid compute type raises ValueError."""
        with pytest.raises(ValueError):
            EngineConfig(compute_type="int16")


class TestCorrectionConfig:
    """Tests for CorrectionConfig validation."""

    def test_valid_correction_config(self):
        """Test creating valid correction config."""
        config = CorrectionConfig(
            auto_apply_threshold=3,
            fuzzy_match_score=80,
            max_hotwords=10,
        )
        assert config.auto_apply_threshold == 3

    def test_correction_config_auto_apply_threshold_negative(self):
        """Test that negative auto_apply_threshold raises ValueError."""
        with pytest.raises(ValueError):
            CorrectionConfig(auto_apply_threshold=-1)

    def test_correction_config_auto_apply_threshold_zero_valid(self):
        """Test that auto_apply_threshold=0 is valid."""
        config = CorrectionConfig(auto_apply_threshold=0)
        assert config.auto_apply_threshold == 0

    def test_correction_config_fuzzy_match_score_too_low(self):
        """Test that fuzzy_match_score < 0 raises ValueError."""
        with pytest.raises(ValueError):
            CorrectionConfig(fuzzy_match_score=-10)

    def test_correction_config_fuzzy_match_score_too_high(self):
        """Test that fuzzy_match_score > 100 raises ValueError."""
        with pytest.raises(ValueError):
            CorrectionConfig(fuzzy_match_score=101)

    def test_correction_config_fuzzy_match_score_valid_range(self):
        """Test valid fuzzy_match_score range."""
        config1 = CorrectionConfig(fuzzy_match_score=0)
        config2 = CorrectionConfig(fuzzy_match_score=100)
        assert config1.fuzzy_match_score == 0
        assert config2.fuzzy_match_score == 100

    def test_correction_config_max_hotwords_negative(self):
        """Test that negative max_hotwords raises ValueError."""
        with pytest.raises(ValueError):
            CorrectionConfig(max_hotwords=-1)

    def test_correction_config_max_hotwords_zero_valid(self):
        """Test that max_hotwords=0 is valid."""
        config = CorrectionConfig(max_hotwords=0)
        assert config.max_hotwords == 0


class TestSecurityConfig:
    """Tests for SecurityConfig validation."""

    def test_valid_security_config(self):
        """Test creating valid security config."""
        config = SecurityConfig(
            allow_python_scripts=True,
            allow_yaml_macros=True,
            allow_program_launch=True,
            dictation_only=False,
        )
        assert config.allow_python_scripts is True

    def test_security_config_defaults(self):
        """Test SecurityConfig default values."""
        config = SecurityConfig()
        assert config.allow_python_scripts is True
        assert config.allow_yaml_macros is True
        assert config.allow_program_launch is True
        assert config.dictation_only is False

    def test_security_config_dictation_only_disables_all(self):
        """Test that dictation_only can be set."""
        config = SecurityConfig(dictation_only=True)
        assert config.dictation_only is True


class TestUIConfig:
    """Tests for UIConfig validation."""

    def test_valid_ui_config(self):
        """Test creating valid UI config."""
        config = UIConfig(
            backend="auto",
            theme="dark",
        )
        assert config.backend == "auto"

    def test_ui_config_defaults(self):
        """Test UIConfig default values."""
        config = UIConfig()
        assert config.backend == "auto"
        assert config.theme == "system"

    def test_ui_config_correction_shortcut(self):
        """Test UI config correction shortcut."""
        config = UIConfig(correction_shortcut="ctrl+shift+c")
        assert config.correction_shortcut == "ctrl+shift+c"


class TestConfigIntegration:
    """Integration tests for full Config object."""

    def test_full_config_creation(self):
        """Test creating a complete Config object."""
        config = Config()
        assert config.audio is not None
        assert config.engine is not None
        assert config.correction is not None
        assert config.ui is not None
        assert config.security is not None

    def test_full_config_with_invalid_audio(self):
        """Test that Config creation fails with invalid audio config."""
        with pytest.raises(ValueError):
            Config(audio=AudioConfig(vad_threshold=2.0))

    def test_full_config_with_invalid_engine(self):
        """Test that Config creation fails with invalid engine config."""
        with pytest.raises(ValueError):
            Config(engine=EngineConfig(beam_size=0))

    def test_full_config_with_invalid_correction(self):
        """Test that Config creation fails with invalid correction config."""
        with pytest.raises(ValueError):
            Config(correction=CorrectionConfig(fuzzy_match_score=150))

    def test_config_defaults(self):
        """Test Config default values."""
        config = Config()
        assert config.audio.vad_threshold == 0.5
        assert config.engine.backend == "auto"
        assert config.correction.fuzzy_match_score == 85
        assert config.ui.backend == "auto"

    def test_config_save_and_load_roundtrip(self):
        """Test that config can be saved and loaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config1 = Config()
            config_file = Path(tmpdir) / "config.yaml"

            config1.save(config_file)
            assert config_file.exists()

            config2 = Config.load(config_file)
            assert config2.engine.backend == config1.engine.backend
            assert config2.audio.sample_rate == config1.audio.sample_rate
            assert config2.correction.fuzzy_match_score == config1.correction.fuzzy_match_score


class TestConfigValidationEdgeCases:
    """Edge case tests for config validation."""

    def test_audio_config_all_minimum_valid_values(self):
        """Test minimum valid values for audio config."""
        config = AudioConfig(
            vad_threshold=0.0,
            channels=1,
            sample_rate=8000,
            silence_duration_ms=0,
            min_speech_duration_ms=0,
            network_port=1,
        )
        assert config.vad_threshold == 0.0
        assert config.network_port == 1

    def test_audio_config_all_maximum_valid_values(self):
        """Test maximum valid values for audio config."""
        config = AudioConfig(
            vad_threshold=1.0,
            network_port=65535,
        )
        assert config.vad_threshold == 1.0
        assert config.network_port == 65535

    def test_correction_config_boundary_values(self):
        """Test boundary values for correction config."""
        config = CorrectionConfig(
            auto_apply_threshold=0,
            fuzzy_match_score=0,
            max_hotwords=0,
        )
        assert config.auto_apply_threshold == 0
        assert config.fuzzy_match_score == 0
        assert config.max_hotwords == 0

    def test_engine_config_all_valid_backends(self):
        """Test that engine accepts all documented backends."""
        for backend in ["auto", "faster-whisper", "openai-whisper", "openai-api"]:
            config = EngineConfig(backend=backend)
            assert config.backend == backend

    def test_engine_config_device_and_compute_combinations(self):
        """Test various device and compute_type combinations."""
        combinations = [
            ("auto", "auto"),
            ("cuda", "float16"),
            ("cpu", "int8"),
        ]
        for device, compute_type in combinations:
            config = EngineConfig(device=device, compute_type=compute_type)
            assert config.device == device
            assert config.compute_type == compute_type
