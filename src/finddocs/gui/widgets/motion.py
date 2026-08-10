"""Delikatny ruch i cienie interfejsu.

Fluent uzywa ruchu oszczednie: pojawienie panelu albo banera to jedno krotkie
przejscie, nic nie skacze i nic nie sprezynuje. Ruch jest calkowicie wylaczany,
gdy uzytkownik ograniczyl animacje w ustawieniach systemu, oraz na platformie
``offscreen``, gdzie nikt go nie widzi, a testy maja byc deterministyczne.

Cien wystepuje wylacznie w motywie jasnym i tylko na dwoch powierzchniach:
polu zapytania i kartach wynikow. Wiecej cieni to mniej cienia.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QWidget

from finddocs.gui.theme import Palette

#: Czas pojedynczego przejscia. Fluent trzyma sie zakresu 100-200 ms.
DURATION_MS = 150

#: Rozmycie miekkiego cienia i jego przesuniecie w dol.
SHADOW_BLUR = 14
SHADOW_OFFSET_Y = 2

#: Krycie cienia w skali 0-255. Okolo 8 procent.
SHADOW_ALPHA = 20

#: Wynik odczytu ustawien systemowych, liczony raz.
_animations_enabled: bool | None = None


def _read_system_setting() -> bool:
    """Czy system pozwala na animacje interfejsu.

    Windows: ustawienie ,,Pokaz animacje w systemie Windows''. Brak mozliwosci
    odczytu traktujemy jako zgode, bo to stan domyslny systemu.
    """
    app = QGuiApplication.instance()
    if isinstance(app, QGuiApplication) and app.platformName() == "offscreen":
        return False
    if sys.platform != "win32":
        return True
    import ctypes

    spi_get_client_area_animation = 0x1042
    value = ctypes.c_int(1)
    try:
        ok = ctypes.windll.user32.SystemParametersInfoW(
            spi_get_client_area_animation, 0, ctypes.byref(value), 0
        )
    except OSError:
        return True
    return bool(value.value) if ok else True


def animations_enabled() -> bool:
    """Czy ruch interfejsu jest wlaczony."""
    global _animations_enabled
    if _animations_enabled is None:
        _animations_enabled = _read_system_setting()
    return _animations_enabled


def fade_in(widget: QWidget, duration: int = DURATION_MS) -> None:
    """Plynne pojawienie kontrolki. Bez animacji nic nie robi."""
    if not animations_enabled():
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    # Efekt krycia zostawiony na stale przeszkadzalby efektowi cienia,
    # wiec po przejsciu jest zdejmowany.
    animation.finished.connect(
        lambda: widget.setGraphicsEffect(None)  # type: ignore[arg-type]
    )
    animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


#: Wartosc QWIDGETSIZE_MAX: zdjecie ograniczenia wysokosci po animacji.
_NO_MAX_HEIGHT = 16777215


def expand_vertically(widget: QWidget, duration: int = DURATION_MS) -> None:
    """Rozwija kontrolke od zera do naturalnej wysokosci."""
    if not animations_enabled():
        return
    target = widget.sizeHint().height()
    if target <= 0:
        return
    widget.setMaximumHeight(0)
    animation = QPropertyAnimation(widget, b"maximumHeight", widget)
    animation.setDuration(duration)
    animation.setStartValue(0)
    animation.setEndValue(target)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.finished.connect(lambda: widget.setMaximumHeight(_NO_MAX_HEIGHT))
    animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


def apply_soft_shadow(widget: QWidget, palette: Palette) -> None:
    """Miekki cien pod kluczowa powierzchnia. Tylko motyw jasny.

    W ciemnym motywie cien na ciemnym tle jest niewidoczny, a probowanie
    go rozjasnianiem daje poswiate, ktorej Fluent unika.
    """
    if palette.variant != "light":
        widget.setGraphicsEffect(None)  # type: ignore[arg-type]
        return
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(SHADOW_BLUR)
    shadow.setOffset(0, SHADOW_OFFSET_Y)
    shadow.setColor(QColor(0, 0, 0, SHADOW_ALPHA))
    widget.setGraphicsEffect(shadow)


__all__ = [
    "DURATION_MS",
    "SHADOW_ALPHA",
    "SHADOW_BLUR",
    "SHADOW_OFFSET_Y",
    "animations_enabled",
    "apply_soft_shadow",
    "expand_vertically",
    "fade_in",
]
