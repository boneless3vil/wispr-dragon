"""Tests for the mic-state icon assets + mapping (wispr_dragon.ui.icons)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from wispr_dragon import icons  # noqa: E402
from wispr_dragon.ui.mic_state import MicState  # noqa: E402


@pytest.fixture(scope="module")
def _app():
    """A QApplication is required to construct QIcon/QPixmap objects."""
    app = QApplication.instance() or QApplication([])
    yield app


def test_icons_module_does_not_import_the_desktop_ui():
    """The headless client's tray imports icons — it must stay UI-free.

    `wispr_dragon.ui.__init__` eagerly imports the whole desktop stack, pulling
    in server-side deps (rapidfuzz) the lean client venv doesn't install. When
    icons lived under ui/, that silently disabled the client's tray icon.
    Run in a subprocess so a clean sys.modules is guaranteed.
    """
    import subprocess
    import sys as _sys

    code = (
        "import sys; import wispr_dragon.icons; "
        "assert 'wispr_dragon.ui' not in sys.modules, "
        "'importing icons must not pull in wispr_dragon.ui'"
    )
    subprocess.run([_sys.executable, "-c", code], check=True)


def test_asset_files_exist():
    """Both PNGs must be present in the package so the wheel can bundle them."""
    assert icons.MIC_ON_PATH.exists(), icons.MIC_ON_PATH
    assert icons.MIC_OFF_PATH.exists(), icons.MIC_OFF_PATH


def test_icons_load_non_null(_app):
    """Assets load as real (non-null) QIcons, not empty placeholders."""
    icons._cache.clear()
    assert icons.mic_on_icon() is not None
    assert icons.mic_off_icon() is not None
    assert not icons.mic_on_icon().isNull()
    assert not icons.mic_off_icon().isNull()


def test_icons_are_cached(_app):
    """Repeated lookups return the same cached QIcon (no disk re-read)."""
    icons._cache.clear()
    assert icons.mic_on_icon() is icons.mic_on_icon()
    assert icons.mic_off_icon() is icons.mic_off_icon()


def test_state_mapping(_app):
    """HOT → on icon; OFF and STANDBY → off icon."""
    icons._cache.clear()
    assert icons.icon_for_mic_state(MicState.HOT) is icons.mic_on_icon()
    assert icons.icon_for_mic_state(MicState.OFF) is icons.mic_off_icon()
    assert icons.icon_for_mic_state(MicState.STANDBY) is icons.mic_off_icon()
