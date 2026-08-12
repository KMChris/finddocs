"""Okno parametrow importu modelu embeddingow.

Zbiera dane potrzebne przed importem: zrodlo (katalog albo repozytorium
Hugging Face), nazwe docelowa, pooling, przedrostki i kwantyzacje.
Sam import wykonuje karta modelu na ekranie Zrodla i konfiguracja
(``finddocs.gui.config_cards``), w puli watkow, poza tym oknem.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from finddocs.gui import i18n
from finddocs.gui.dialogs import show_warning
from finddocs.providers.model_store import ImportOptions, looks_like_repo_id

#: Tryby poolingu do wyboru przy imporcie. Pusta wartosc oznacza wykrycie.
_POOLING_CHOICES: tuple[tuple[str, str], ...] = (
    ("wykryj automatycznie", ""),
    ("CLS (pierwszy token)", "cls"),
    ("uśrednianie (mean)", "mean"),
    ("brak (model zwraca gotowy wektor)", "none"),
)


class ModelImportDialog(QDialog):
    """Parametry importu modelu: zrodlo, nazwa, pooling, kwantyzacja, przedrostki."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        source_label: str = "",
        repo_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(i18n.MODEL_IMPORT_TITLE)
        self.setMinimumWidth(520)
        self._repo_mode = repo_mode

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        self.repo_edit = QLineEdit()
        self.repo_edit.setPlaceholderText("sdadas/mmlw-retrieval-roberta-base")
        if repo_mode:
            form.addRow(i18n.MODEL_IMPORT_REPO, self.repo_edit)
        else:
            source = QLabel(source_label)
            source.setWordWrap(True)
            form.addRow(i18n.MODEL_IMPORT_SOURCE, source)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(i18n.MODEL_IMPORT_NAME_HINT)
        form.addRow(i18n.MODEL_IMPORT_NAME, self.name_edit)

        self.pooling_combo = QComboBox()
        for label, value in _POOLING_CHOICES:
            self.pooling_combo.addItem(label, value)
        form.addRow(i18n.MODEL_IMPORT_POOLING, self.pooling_combo)

        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText(i18n.MODEL_IMPORT_PREFIX_HINT)
        form.addRow(i18n.MODEL_QUERY_PREFIX, self.query_edit)

        self.passage_edit = QLineEdit()
        self.passage_edit.setPlaceholderText(i18n.MODEL_IMPORT_PREFIX_HINT)
        form.addRow(i18n.MODEL_PASSAGE_PREFIX, self.passage_edit)

        self.quantize_check = QCheckBox(i18n.MODEL_IMPORT_QUANTIZE)
        self.quantize_check.setChecked(True)
        form.addRow("", self.quantize_check)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(i18n.MODEL_IMPORT_TITLE)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.BUTTON_CANCEL)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self) -> None:
        if self._repo_mode and not looks_like_repo_id(self.repo_id()):
            show_warning(self, i18n.MODEL_IMPORT_REPO_INVALID)
            return
        self.accept()

    def repo_id(self) -> str:
        return self.repo_edit.text().strip()

    def to_options(self) -> ImportOptions:
        query = self.query_edit.text()
        passage = self.passage_edit.text()
        return ImportOptions(
            name=self.name_edit.text().strip(),
            quantize=self.quantize_check.isChecked(),
            pooling=str(self.pooling_combo.currentData()),
            query_prefix=query if query else None,
            passage_prefix=passage if passage else None,
        )


__all__ = ["ModelImportDialog"]
