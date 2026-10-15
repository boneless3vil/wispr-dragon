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

import atexit
import os
import shutil
import tempfile

# Point the home directory at a throwaway dir BEFORE any wispr_dragon module is
# imported: several modules resolve ~/.wispr_dragon (dictionary, commands,
# client config) at import time, and a test that writes through one of those
# would otherwise touch the developer's real data.
_SANDBOX_HOME = tempfile.mkdtemp(prefix="wispr_test_home_")
os.environ["HOME"] = os.environ["USERPROFILE"] = _SANDBOX_HOME
atexit.register(shutil.rmtree, _SANDBOX_HOME, ignore_errors=True)
# Headless Qt for every widget test (CI sets it too; this covers local runs).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

import wispr_dragon.config as config_mod  # noqa: E402


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
