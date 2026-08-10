"""Testy ruchu i cieni: wylaczanie animacji i zasieg cienia."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QWidget

from finddocs.gui.theme import DARK, LIGHT
from finddocs.gui.widgets import motion


def test_animacje_sa_wylaczone_na_platformie_offscreen(qapp: QApplication) -> None:
    """Na platformie bez ekranu ruch nie ma widza, a testy maja byc deterministyczne."""
    assert motion.animations_enabled() is False


def test_ruch_bez_animacji_nie_zmienia_kontrolki(qtbot: object, qapp: QApplication) -> None:
    widget = QWidget()
    qtbot.addWidget(widget)  # type: ignore[attr-defined]

    motion.fade_in(widget)
    assert widget.graphicsEffect() is None

    motion.expand_vertically(widget)
    assert widget.maximumHeight() == 16777215


def test_cien_tylko_w_jasnym_motywie(qtbot: object, qapp: QApplication) -> None:
    """W ciemnym motywie cien na ciemnym tle to poswiata, wiec go nie ma."""
    widget = QWidget()
    qtbot.addWidget(widget)  # type: ignore[attr-defined]

    motion.apply_soft_shadow(widget, LIGHT)
    assert widget.graphicsEffect() is not None

    motion.apply_soft_shadow(widget, DARK)
    assert widget.graphicsEffect() is None
