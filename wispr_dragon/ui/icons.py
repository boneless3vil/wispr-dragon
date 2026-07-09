"""Application icon assets and mic-state → icon mapping.

Two bundled PNGs back the mic indicator:

- ``mic_on.png``  — red, glowing: the mic is HOT (capturing + transcribing).
- ``mic_off.png`` — flat black: the mic is OFF (or STANDBY, i.e. open but asleep;
  with only two artworks, standby reuses the off icon — the tray tooltip/label
  still distinguishes it).

**Theme awareness.** ``mic_off.png`` is solid black, which is invisible against a
dark system tray — and Windows ships a dark taskbar by default. When the tray is
dark we re-tint the artwork white, preserving its alpha silhouette. ``mic_on.png``
is left alone: its red glow reads on either background.

Icons are loaded lazily and cached (keyed by path *and* tint), so repeated state
changes don't re-read disk or re-paint. ``icon_for_mic_state`` is the single
mapping the tray and windows share, so the indicator can't disagree with itself.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_ASSETS = Path(__file__).resolve().parent / "assets"
MIC_ON_PATH = _ASSETS / "mic_on.png"
MIC_OFF_PATH = _ASSETS / "mic_off.png"

# Cache keyed by (path, tint) -> Optional[QIcon]. A path that fails to load
# caches None so we don't retry on every state transition.
_cache: dict = {}


def system_prefers_dark_tray() -> bool:
    """True when the system tray / taskbar is dark, so dark art needs inverting.

    Windows exposes this as ``SystemUsesLightTheme`` (0 = dark taskbar) — note
    this is distinct from ``AppsUseLightTheme``, which governs app windows, not
    the tray. Elsewhere, fall back to the Qt palette's lightness.
    """
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            with key:
                value, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
            return value == 0
        except OSError:
            return True  # Windows defaults to a dark taskbar.

    try:
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            return app.palette().window().color().lightness() < 128
    except Exception:  # pragma: no cover - no Qt / no app
        pass
    return False


def _load(path: Path, tint: Optional[str] = None):
    """Return a cached QIcon for ``path``, optionally re-tinted to ``tint``.

    Tinting keeps the artwork's alpha and replaces its color, turning the black
    mic into a white silhouette. Returns None if Qt or the asset is unavailable.
    """
    cache_key = (path, tint)
    if cache_key in _cache:
        return _cache[cache_key]

    icon = None
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap

        if not path.exists():
            logger.warning("Icon asset missing: %s", path)
        else:
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                logger.warning("Icon failed to load (null pixmap): %s", path)
            else:
                if tint:
                    tinted = QPixmap(pixmap.size())
                    tinted.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(tinted)
                    painter.drawPixmap(0, 0, pixmap)
                    # SourceIn paints the fill only where the source is opaque,
                    # so we recolor the glyph and keep its shape.
                    painter.setCompositionMode(
                        QPainter.CompositionMode.CompositionMode_SourceIn
                    )
                    painter.fillRect(tinted.rect(), QColor(tint))
                    painter.end()
                    pixmap = tinted
                icon = QIcon(pixmap)
    except ImportError:
        logger.debug("PyQt6 unavailable; cannot load icon %s", path)

    _cache[cache_key] = icon
    return icon


def mic_on_icon():
    """QIcon for the HOT (recording) state, or None if unavailable."""
    return _load(MIC_ON_PATH)


def mic_off_icon():
    """QIcon for the OFF/STANDBY state, tinted white on a dark tray."""
    tint = "#ffffff" if system_prefers_dark_tray() else None
    return _load(MIC_OFF_PATH, tint)


def icon_for_mic_state(state) -> Optional[object]:
    """Map a MicState to its QIcon. HOT → on icon; OFF/STANDBY → off icon.

    Returns None if Qt or the asset is unavailable so callers can no-op safely.
    """
    from .mic_state import MicState

    return mic_on_icon() if state == MicState.HOT else mic_off_icon()
