"""Tests for engine factory and selection logic."""

import pytest

from wispr_dragon.config import Config
from wispr_dragon.engine import validate_engine_config


@pytest.fixture
def base_config():
    """Create a base config for testing."""
    return Config()


def test_validate_engine_config_openai_api_device_warning(base_config, caplog):
    """Test that openai-api warns about ignored device config."""
    base_config.engine.backend = "openai-api"
    base_config.engine.device = "cuda"

    validate_engine_config(base_config)

    assert "openai-api engine ignores 'device' config" in caplog.text
    assert "cuda" in caplog.text


def test_validate_engine_config_openai_api_compute_type_warning(base_config, caplog):
    """Test that openai-api warns about ignored compute_type config."""
    base_config.engine.backend = "openai-api"
    base_config.engine.compute_type = "int8"

    validate_engine_config(base_config)

    assert "openai-api engine ignores 'compute_type' config" in caplog.text
    assert "int8" in caplog.text


def test_validate_engine_config_openai_api_no_warning_with_auto(base_config, caplog):
    """Test that openai-api doesn't warn when device/compute_type are auto."""
    base_config.engine.backend = "openai-api"
    base_config.engine.device = "auto"
    base_config.engine.compute_type = "auto"

    validate_engine_config(base_config)

    assert "openai-api engine ignores" not in caplog.text


def test_validate_engine_config_faster_whisper_no_warning(base_config, caplog):
    """Test that faster-whisper doesn't generate warnings."""
    base_config.engine.backend = "faster-whisper"
    base_config.engine.device = "cuda"
    base_config.engine.compute_type = "float32"

    validate_engine_config(base_config)

    assert "ignores" not in caplog.text


def test_validate_engine_config_openai_whisper_no_warning(base_config, caplog):
    """Test that openai-whisper doesn't generate warnings."""
    base_config.engine.backend = "openai-whisper"
    base_config.engine.device = "cuda"

    validate_engine_config(base_config)

    assert "ignores" not in caplog.text


def test_validate_engine_config_both_warnings(base_config, caplog):
    """Test both device and compute_type warnings together."""
    base_config.engine.backend = "openai-api"
    base_config.engine.device = "cuda"
    base_config.engine.compute_type = "int8"

    validate_engine_config(base_config)

    assert "device" in caplog.text
    assert "compute_type" in caplog.text


def test_engine_backend_default_is_auto(base_config):
    """Test that default backend is auto."""
    assert base_config.engine.backend == "auto"


def test_validate_engine_config_device_values(base_config, caplog):
    """Test device warnings only for openai-api."""
    for backend in ["faster-whisper", "openai-whisper"]:
        caplog.clear()
        base_config.engine.backend = backend
        base_config.engine.device = "cuda"

        validate_engine_config(base_config)

        assert "ignores" not in caplog.text


def test_validate_engine_config_compute_type_values(base_config, caplog):
    """Test compute_type warnings only for openai-api."""
    for backend in ["faster-whisper", "openai-whisper"]:
        caplog.clear()
        base_config.engine.backend = backend
        base_config.engine.compute_type = "int8"

        validate_engine_config(base_config)

        assert "ignores" not in caplog.text
