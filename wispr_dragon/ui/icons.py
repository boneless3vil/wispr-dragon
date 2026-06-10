"""Application icon assets and mic-state → icon mapping.

Two bundled PNGs back the mic indicator:

- ``mic_on.png``  — red, glowing: the mic is HOT (capturing + transcribing).
- ``mic_off.png`` — flat black: the mic is OFF (or STANDBY, i.e. open but asleep;
  with only two artworks, standby reuses the off icon — the tray tooltip/label
  still distinguishes it).

Icons are loaded lazily and cached, so repeated state changes don't re-read disk.
``icon_for_mic_state`` is the single mapping both the tray and the window use, so
the indicator can never disagree with itself.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_ASSETS = Path(__file__).resolve().parent / "assets"
MIC_ON_PATH = _ASSETS / "mic_on.png"
MIC_OFF_PATH = _ASSETS / "mic_off.png"

# QIcon cache keyed by path, populated on first use. Holds Optional[QIcon];
# a path that fails to load caches None so we don't retry every transition.
_cache: dict = {}


def _load(path: Path):
    """Return a cached QIcon for ``path`` (or None if Qt/asset unavailable)."""
    if path in _cache:
        return _cache[path]
    icon = None
    try:
        from PyQt6.QtGui import QIcon

        if path.exists():
            loaded = QIcon(str(path))
            icon = loaded if not loaded.isNull() else None
            if icon is None:
                logger.warning("Icon failed to load (null pixmap): %s", path)
        else:
            logger.warning("Icon asset missing: %s", path)
    except ImportError:
        logger.debug("PyQt6 unavailable; cannot load icon %s", path)
    _cache[path] = icon
    return icon


def mic_on_icon():
    """QIcon for the HOT (recording) state, or None if unavailable."""
    return _load(MIC_ON_PATH)


def mic_off_icon():
    """QIcon for the OFF/STANDBY (not capturing) state, or None if unavailable."""
    return _load(MIC_OFF_PATH)


def icon_for_mic_state(state) -> Optional[object]:
    """Map a MicState to its QIcon. HOT → on icon; OFF/STANDBY → off icon.

    Returns None if Qt or the asset is unavailable so callers can no-op safely.
    """
    from .mic_state import MicState

    return mic_on_icon() if state == MicState.HOT else mic_off_icon()
