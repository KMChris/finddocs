"""Testy tlumienia okien konsoli przy odpytywaniu wersji systemu."""

from __future__ import annotations

import platform
import subprocess
import sys
from typing import Any

import pytest

from finddocs import win_console

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="okna konsoli dotycza wylacznie Windows"
)


@pytest.fixture(autouse=True)
def restore_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """Przywraca stan globalny: podmiana dotyka biblioteki standardowej."""
    monkeypatch.setattr(platform, "_syscmd_ver", platform._syscmd_ver)  # type: ignore[attr-defined]
    monkeypatch.setattr(win_console, "_patched", False)


def test_version_read_without_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    assert win_console.suppress_console_windows() is True

    def refuse(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("wersji systemu nie wolno pytac procesem potomnym")

    monkeypatch.setattr(subprocess, "check_output", refuse)
    release, version, _csd, _ptype = platform.win32_ver()

    winver = sys.getwindowsversion()
    expected = ".".join(str(part) for part in (winver.platform_version or winver[:3]))
    assert version == expected
    assert release


def test_second_call_does_nothing() -> None:
    assert win_console.suppress_console_windows() is True
    assert win_console.suppress_console_windows() is False


def test_flag_hides_console_of_child_process() -> None:
    assert win_console.NO_CONSOLE_WINDOW == subprocess.CREATE_NO_WINDOW
