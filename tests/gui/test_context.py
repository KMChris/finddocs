"""Testy kontekstu aplikacji: propagacja konfiguracji do serwisow.

Widoki podmieniaja ``context.config`` na nowy obiekt (``with_source`` zwraca
kopie). Regresja polegala na tym, ze ``JobRunner`` trzymal stara referencje
i zadanie indeksowania konczylo sie komunikatem o braku zrodel, dopoki
uzytkownik nie uruchomil aplikacji ponownie.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from finddocs.config import LocalDirSourceSettings, SourceConfig
from finddocs.gui.context import AppContext
from finddocs.gui.indexing_view import IndexingView
from finddocs.types import SourceKind

TIMEOUT_MS = 20_000


def _local_source(root: Path) -> SourceConfig:
    return SourceConfig(
        source_id=f"local-{uuid.uuid4().hex[:8]}",
        kind=SourceKind.LOCAL_DIR,
        label=root.name,
        local=LocalDirSourceSettings(root_path=str(root)),
    )


@pytest.mark.gui
def test_save_propagates_config_to_services(gui_context: AppContext, tmp_path: Path) -> None:
    """Po zapisie nowej konfiguracji indeks, wyszukiwarka i wykonawca widza ja od razu."""
    old_config = gui_context.config

    gui_context.config = gui_context.config.with_source(_local_source(tmp_path))
    gui_context.save()

    assert gui_context.config is not old_config
    assert gui_context.require_index().config is gui_context.config
    assert gui_context.require_runner().config is gui_context.config
    assert gui_context.require_search().settings is gui_context.config.search


@pytest.mark.gui
def test_runner_reads_config_at_job_start(gui_context: AppContext, tmp_path: Path) -> None:
    """Wykonawca pobiera konfiguracje przy starcie zadania, nie przy utworzeniu."""
    gui_context.config = gui_context.config.with_source(_local_source(tmp_path))

    runner = gui_context.require_runner()
    assert runner.config is not gui_context.config

    # Ten sam mechanizm, ktorego uzywa _run_job przed utworzeniem zadania.
    assert runner._config_provider is not None
    assert runner._config_provider() is gui_context.config


@pytest.mark.gui
def test_wykonawca_nie_mnozy_odbiorcow_postepu(
    qtbot: object, gui_context: AppContext, gui_corpus: Path
) -> None:
    """Widok zglasza sie przy kazdym zleceniu, a odbiorca ma zostac jeden.

    Powtorzenia mnozyly te sama migawke: po kilku zadaniach w jednej sesji
    interfejs przerysowywal postep tyle razy, ile zadan uruchomiono.
    """
    view = IndexingView(gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    gui_context.config = gui_context.config.with_source(_local_source(gui_corpus))
    gui_context.save()
    runner = gui_context.require_runner()

    for _ in range(3):
        with qtbot.waitSignal(view.index_changed, timeout=TIMEOUT_MS):  # type: ignore[attr-defined]
            view.start_scan()

    assert runner._progress_callbacks.count(view.bridge.publish) == 1
    assert runner._completion_callbacks.count(view.bridge.publish_completion) == 1


@pytest.mark.gui
def test_indexing_sees_source_added_after_startup(
    qtbot: object, gui_context: AppContext, gui_corpus: Path
) -> None:
    """Zrodlo dodane po uruchomieniu aplikacji jest indeksowane bez restartu."""
    view = IndexingView(gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]

    # Dokladnie to robi SourcesView.add_local_source: podmiana obiektu i zapis.
    gui_context.config = gui_context.config.with_source(_local_source(gui_corpus))
    gui_context.save()

    with qtbot.waitSignal(view.index_changed, timeout=TIMEOUT_MS):  # type: ignore[attr-defined]
        view.start_scan()

    assert gui_context.require_index().status().indexed_documents > 0
