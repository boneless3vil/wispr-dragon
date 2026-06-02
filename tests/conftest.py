"""Shared pytest fixtures + global safety nets.

The most important thing here is `_isolate_user_config`: several tests construct
a default ``Config()`` and call ``.save()`` *with no path*, which resolves to the
real ``~/.wispr_dragon/config.yaml``. On a developer machine that path is
writable, so those tests would silently overwrite the live config with pure
dataclass defaults (device=cpu, empty api_key) — clobbering GPU + auth settings.
This autouse fixture redirects the default config path to a throwaway temp dir
for the whole session, so no test can ever touch the real user config.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import wispr_dragon.config as config_mod


@pytest.fixture(autouse=True, scope="session")
def _isolate_user_config(tmp_path_factory):
    """Redirect the default config/user paths away from the real home dir."""
    sandbox = tmp_path_factory.mktemp("wispr_user_dir")
    originals = {
        "DEFAULT_USER_DIR": config_mod.DEFAULT_USER_DIR,
        "DEFAULT_CONFIG_PATH": config_mod.DEFAULT_CONFIG_PATH,
    }
    config_mod.DEFAULT_USER_DIR = sandbox
    config_mod.DEFAULT_CONFIG_PATH = sandbox / "config.yaml"
    try:
        yield sandbox
    finally:
        for name, value in originals.items():
            setattr(config_mod, name, value)
