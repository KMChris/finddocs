"""Teksty interfejsu w jezyku polskim.

Wszystkie napisy widoczne dla uzytkownika sa w jednym miejscu. Ulatwia to korekte
jezykowa i pozniejsze dodanie innej wersji jezykowej bez szukania po widokach.
"""

from __future__ import annotations

from finddocs.types import DocumentStatus, JobState, MatchKind, SearchMode

APP_TITLE = "FindDocs"
APP_SUBTITLE = "Lokalna wyszukiwarka dokumentów"

# --- nawigacja ---------------------------------------------------------------

NAV_SEARCH = "Wyszukiwanie"
NAV_SOURCES = "Źródła i konfiguracja"
NAV_INDEXING = "Indeksowanie"
NAV_REPORT = "Raport pokrycia"
NAV_DIAGNOSTICS = "Diagnostyka"

# --- ekran wyszukiwania ------------------------------------------------------

SEARCH_PLACEHOLDER = "Wpisz zapytanie, na przykład: procedura przelewów z 24.07.2015"
SEARCH_BUTTON = "Szukaj"
SEARCH_CANCEL = "Przerwij"
SEARCH_FILTERS = "Filtry"
SEARCH_FILTERS_CLEAR = "Wyczyść filtry"
SEARCH_NO_RESULTS = "Brak wyników dla tego zapytania."
SEARCH_EMPTY_STATE = (
    "Wpisz zapytanie i naciśnij Enter.\n\n"
    "Tryb Dokładne znajduje wszystkie dokumenty zawierające podane słowa, numery i daty.\n"
    "Tryb Semantyczne szuka dokumentów powiązanych znaczeniowo.\n"
    "Tryb Hybrydowe łączy oba podejścia."
)
SEARCH_RUNNING = "Wyszukiwanie w toku..."
SEARCH_INDEX_EMPTY = (
    "Indeks jest pusty. Przejdź do ekranu Indeksowanie i uruchom skanowanie źródła."
)

MODE_LABELS: dict[SearchMode, str] = {
    SearchMode.HYBRID: "Hybrydowe",
    SearchMode.EXACT: "Dokładne",
    SearchMode.SEMANTIC: "Semantyczne",
}

MODE_HINTS: dict[SearchMode, str] = {
    SearchMode.HYBRID: "Łączy dopasowania dosłowne z podobieństwem znaczeniowym.",
    SearchMode.EXACT: "Zwraca wszystkie dokumenty zawierające podane wartości.",
    SearchMode.SEMANTIC: "Ranking przybliżony. Nie gwarantuje kompletności wyników.",
}

MATCH_LABELS: dict[MatchKind, str] = {
    MatchKind.EXACT: "dopasowanie dokładne",
    MatchKind.SEMANTIC: "dopasowanie semantyczne",
    MatchKind.HYBRID: "dopasowanie hybrydowe",
}

RESULT_OPEN = "Otwórz dokument"
RESULT_OPEN_LOCATION = "Otwórz lokalizację"
RESULT_COPY_LINK = "Kopiuj odnośnik"
RESULT_OCR_BADGE = "OCR"
RESULT_MORE_CHUNKS = "Pasujących fragmentów w tym dokumencie: {count}"
RESULT_MODIFIED = "Zmodyfikowano: {value}"
RESULT_INDEXED = "Zaindeksowano: {value}"
RESULT_AUTHOR = "Autor: {value}"
RESULT_SCORE = "Siła dopasowania: {value}"
RESULT_SCORE_TOOLTIP = (
    "Wartość względna wobec najlepszego wyniku na tej stronie. "
    "Nie jest to prawdopodobieństwo ani miara bezwzględna."
)

FILTER_EXTENSION = "Typ pliku"
FILTER_SOURCE = "Źródło"
FILTER_LIBRARY = "Biblioteka"
FILTER_AUTHOR = "Autor"
FILTER_PATH = "Katalog albo lokalizacja"
FILTER_DATE_FROM = "Data od"
FILTER_DATE_TO = "Data do"
FILTER_OCR = "Tylko dokumenty z OCR"
FILTER_ANY = "wszystkie"

PAGINATION_PREVIOUS = "Poprzednia"
PAGINATION_NEXT = "Następna"
PAGINATION_STATUS = "Strona {page} z {pages}"
RESULTS_COUNT_EXACT = "Znaleziono {count} dokumentów"
RESULTS_COUNT_APPROX = "Znaleziono co najmniej {count} dokumentów"
RESULTS_TOOK = "czas: {ms} ms"

# --- ekran zrodel ------------------------------------------------------------

SOURCES_TITLE = "Źródła dokumentów"
SOURCES_ADD_LOCAL = "Dodaj katalog lokalny"
SOURCES_ADD_SHAREPOINT = "Dodaj SharePoint"
SOURCES_TEST = "Testuj połączenie"
SOURCES_REMOVE = "Usuń źródło"
SOURCES_TOGGLE = "Włącz albo wyłącz"
SOURCES_EMPTY = "Nie skonfigurowano żadnego źródła."
SOURCES_DEMO = "Wygeneruj zbiór demonstracyjny"
SOURCES_SIGN_IN = "Zaloguj do SharePoint"
SOURCES_SIGN_OUT = "Wyloguj"

STORAGE_TITLE = "Przechowywanie indeksu"
STORAGE_PATH = "Katalog danych"
STORAGE_CHANGE = "Zmień katalog"
STORAGE_FREE = "Wolne miejsce: {value}"
STORAGE_INDEX_SIZE = "Rozmiar indeksu: {value}"

MODEL_TITLE = "Model wyszukiwania semantycznego"
MODEL_CURRENT = "Model: {value}"
MODEL_DIMENSION = "Wymiar wektora: {value}"
MODEL_MISSING = (
    "Model nie został znaleziony. Wyszukiwanie semantyczne i hybrydowe są niedostępne, "
    "tryb dokładny działa normalnie."
)
MODEL_SEMANTIC_DISABLED = (
    "Indeksowanie semantyczne jest wyłączone w ustawieniach. Tryb dokładny działa normalnie."
)

# --- okno ustawien modelu ----------------------------------------------------

MODEL_SETTINGS_TITLE = "Ustawienia modelu"
MODEL_SETTINGS_BUTTON = "Ustawienia..."
MODEL_QUERY_PREFIX = "Przedrostek zapytania"
MODEL_PASSAGE_PREFIX = "Przedrostek treści"
MODEL_PREFIX_HINT = (
    "Przedrostki są doklejane do tekstu przed policzeniem wektora. Model MMLW "
    "wymaga przedrostka „zapytanie: ” wyłącznie dla zapytań, rodzina E5 "
    "wymaga „query: ” i „passage: ”. Zmiana przedrostków wymaga "
    "przebudowy części semantycznej indeksu."
)
MODEL_PREFIX_NOT_INSTALLED = (
    "Model nie jest zainstalowany, więc przedrostki nie zostały zapisane. "
    "Zainstaluj model albo wybierz go jako aktywny i spróbuj ponownie."
)
MODEL_SEMANTIC_TOGGLE = "Włącz indeksowanie i wyszukiwanie semantyczne"
MODEL_SEMANTIC_HINT = (
    "Po wyłączeniu nowe dokumenty są indeksowane tylko pełnotekstowo, a tryby "
    "semantyczny i hybrydowy przestają działać. Po ponownym włączeniu wystarczy "
    "zwykłe skanowanie: brakujące wektory zostaną uzupełnione automatycznie."
)
MODEL_IMPORT_DISK = "Importuj z dysku..."
MODEL_IMPORT_HF = "Pobierz z Hugging Face..."
MODEL_IMPORT_TITLE = "Import modelu"
MODEL_IMPORT_SOURCE = "Źródło"
MODEL_IMPORT_NAME = "Nazwa modelu"
MODEL_IMPORT_NAME_HINT = "puste pole oznacza nazwę z katalogu albo repozytorium"
MODEL_IMPORT_POOLING = "Pooling"
MODEL_IMPORT_QUANTIZE = "Kwantyzuj do INT8 (mniejszy i szybszy model)"
MODEL_IMPORT_PREFIX_HINT = "puste pole oznacza wykrycie automatyczne"
MODEL_IMPORT_REPO = "Repozytorium Hugging Face"
MODEL_IMPORT_REPO_INVALID = (
    "Podaj identyfikator repozytorium w formacie organizacja/nazwa, "
    "na przykład sdadas/mmlw-retrieval-roberta-base."
)
MODEL_IMPORT_RUNNING = "Trwa import modelu. Duże modele mogą wymagać kilku minut..."
MODEL_IMPORT_DONE = "Zaimportowano model: {name}"
MODEL_IMPORT_OVERWRITE = "Model „{name}” jest już zainstalowany. Nadpisać jego pliki?"
MODEL_DOWNLOAD_CONSENT = (
    "Pobranie modelu wymaga jednorazowego połączenia z Hugging Face.\n"
    "Dozwolone adresy: {hosts}.\n\nZgadzasz się na to połączenie?"
)
MODEL_ACTIVATE_PROMPT = (
    "Ustawić model „{name}” jako aktywny?\n"
    "Zmiana modelu wymaga przebudowy części semantycznej indeksu."
)
MODEL_REBUILD_REQUIRED = (
    "Zmiana wymaga przebudowy części semantycznej indeksu.\n"
    "Uruchom pełne przeindeksowanie na ekranie Indeksowanie.\n"
    "Do tego czasu wyszukiwanie dokładne działa bez zmian."
)
MODEL_RELOAD_WHILE_INDEXING = (
    "Trwa indeksowanie, więc indeks nie został otwarty ponownie. "
    "Zmiany zaczną działać po zakończeniu zadania i ponownym uruchomieniu aplikacji."
)

# --- ekran indeksowania ------------------------------------------------------

INDEXING_TITLE = "Indeksowanie"
INDEXING_START = "Start"
INDEXING_PAUSE = "Pauza"
INDEXING_RESUME = "Wznów"
INDEXING_CANCEL = "Anuluj"
INDEXING_RESCAN = "Skanuj ponownie"
INDEXING_FULL = "Pełne przeindeksowanie"
INDEXING_EXPORT = "Eksportuj raport"
INDEXING_SHOW_ERRORS = "Pokaż błędy"
INDEXING_SHOW_SKIPPED = "Pokaż pliki pominięte"

STAGE_LABEL = "Etap"
STAT_DISCOVERED = "Wykryte pliki"
STAT_PROCESSED = "Przetworzone"
STAT_UNCHANGED = "Niezmienione"
STAT_SKIPPED = "Pominięte"
STAT_FAILED = "Błędy"
STAT_DELETED = "Usunięte ze źródła"
STAT_OCR = "Pliki z OCR"
STAT_OCR_PAGES = "Strony OCR"
STAT_CURRENT = "Przetwarzany plik"
STAT_ELAPSED = "Czas trwania"
STAT_CONNECTION = "Połączenie"
STAT_TEMP = "Przestrzeń tymczasowa"
PROGRESS_UNKNOWN = "Postęp będzie znany po zakończeniu wykrywania plików"
PROGRESS_APPROXIMATE = "Postęp przybliżony: {value}"

JOB_STATE_LABELS: dict[JobState, str] = {
    JobState.QUEUED: "w kolejce",
    JobState.RUNNING: "w toku",
    JobState.PAUSED: "wstrzymane",
    JobState.CANCELLING: "anulowanie",
    JobState.CANCELLED: "anulowane",
    JobState.FAILED: "zakończone błędem",
    JobState.COMPLETED: "zakończone",
}

RESUME_PROMPT = (
    "Poprzednie indeksowanie zostało przerwane. Czy chcesz je wznowić?\n"
    "Dokumenty już przetworzone nie będą przetwarzane ponownie."
)
RESUME_TITLE = "Przerwane indeksowanie"

# --- raport ------------------------------------------------------------------

REPORT_TITLE = "Raport pokrycia"
REPORT_EXPORT_JSON = "Eksportuj do JSON"
REPORT_EXPORT_CSV = "Eksportuj do CSV"
REPORT_REFRESH = "Odśwież"
REPORT_NON_SEARCHABLE = "Dokumenty, których nie można wyszukać"
REPORT_COMPLETE = "Wszystkie wykryte dokumenty są wyszukiwalne."
REPORT_INCOMPLETE = (
    "Zbiór nie jest kompletny. Nie można wyszukać {count} dokumentów. "
    "Szczegóły znajdują się na liście poniżej."
)

# --- diagnostyka -------------------------------------------------------------

DIAG_TITLE = "Diagnostyka"
DIAG_ENVIRONMENT = "Środowisko"
DIAG_COMPONENTS = "Komponenty"
DIAG_INDEX = "Indeks"
DIAG_CONSISTENCY = "Spójność indeksu"
DIAG_NETWORK = "Polityka połączeń sieciowych"
DIAG_EXPORT_BUNDLE = "Eksportuj pakiet diagnostyczny"
DIAG_OPEN_LOGS = "Otwórz katalog logów"
DIAG_CHECK = "Sprawdź spójność"
DIAG_COMPACT = "Kompaktuj indeks wektorowy"
DIAG_BACKUP = "Wykonaj kopię indeksu"
DIAG_LOG_QUERIES = "Zapisuj zapytania w logu diagnostycznym"
DIAG_LOG_QUERIES_HINT = (
    "Domyślnie wyłączone. Włącz tylko na czas diagnozy. Zapytania zostaną zapisane "
    "wyłącznie w lokalnym pliku logu."
)

# --- statusy dokumentow ------------------------------------------------------

STATUS_LABELS: dict[DocumentStatus, str] = {
    DocumentStatus.PENDING: "oczekuje",
    DocumentStatus.INDEXED: "zaindeksowany",
    DocumentStatus.PARTIAL: "zaindeksowany częściowo",
    DocumentStatus.SKIPPED: "pominięty",
    DocumentStatus.UNSUPPORTED: "format nieobsługiwany",
    DocumentStatus.CORRUPTED: "plik uszkodzony",
    DocumentStatus.PASSWORD_PROTECTED: "zabezpieczony hasłem",
    DocumentStatus.EMPTY: "brak treści",
    DocumentStatus.DOWNLOAD_FAILED: "błąd pobierania",
    DocumentStatus.ERROR: "błąd przetwarzania",
    DocumentStatus.DELETED: "usunięty ze źródła",
}

# --- komunikaty ogolne -------------------------------------------------------

BUTTON_OK = "OK"
BUTTON_CANCEL = "Anuluj"
BUTTON_CLOSE = "Zamknij"
BUTTON_SAVE = "Zapisz"
BUTTON_BROWSE = "Przeglądaj..."

ERROR_TITLE = "Wystąpił błąd"
WARNING_TITLE = "Ostrzeżenie"
INFO_TITLE = "Informacja"
CONFIRM_TITLE = "Potwierdzenie"

CONFIRM_REMOVE_SOURCE = (
    "Czy na pewno usunąć źródło {label}?\nDokumenty z tego źródła zostaną usunięte z indeksu."
)
CONFIRM_FULL_REINDEX = (
    "Pełne przeindeksowanie przetworzy wszystkie dokumenty od nowa. "
    "Może to potrwać długo. Kontynuować?"
)

STARTUP_ERROR = (
    "Nie udało się uruchomić aplikacji.\n\n{message}\n\nSzczegóły zapisano w pliku logu:\n{log}"
)

INDEX_INCOMPATIBLE_TITLE = "Indeks wymaga przebudowy"
INDEX_INCOMPATIBLE = (
    "Konfiguracja aplikacji zmieniła się od czasu zbudowania indeksu.\n\n{details}\n\n"
    "Do czasu przebudowy dostępne jest wyszukiwanie dokładne."
)

STARTUP_NOTES_TITLE = "Stan indeksu"
STARTUP_NOTES = (
    "Aplikacja jest gotowa do pracy, ale nie wszystkie funkcje są dostępne.\n\n{details}"
)


def format_bytes(value: int | float) -> str:
    """Rozmiar w postaci czytelnej po polsku, z przecinkiem dziesietnym."""
    units = ("B", "kB", "MB", "GB", "TB")
    size = float(value)
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    if index == 0:
        return f"{int(size)} {units[index]}"
    return f"{size:.1f} {units[index]}".replace(".", ",")


def format_duration(seconds: float) -> str:
    """Czas trwania po polsku."""
    total = int(max(0, seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours} godz. {minutes} min"
    if minutes:
        return f"{minutes} min {secs} s"
    return f"{secs} s"


def format_count(count: int, one: str, few: str, many: str) -> str:
    """Odmiana rzeczownika po liczbie, zgodnie z regulami polskimi."""
    if count == 1:
        return f"{count} {one}"
    last_two = count % 100
    last = count % 10
    if 12 <= last_two <= 14:
        return f"{count} {many}"
    if 2 <= last <= 4:
        return f"{count} {few}"
    return f"{count} {many}"


def documents_count(count: int) -> str:
    return format_count(count, "dokument", "dokumenty", "dokumentów")


def files_count(count: int) -> str:
    return format_count(count, "plik", "pliki", "plików")


__all__ = [
    "APP_SUBTITLE",
    "APP_TITLE",
    "JOB_STATE_LABELS",
    "MATCH_LABELS",
    "MODE_HINTS",
    "MODE_LABELS",
    "STATUS_LABELS",
    "documents_count",
    "files_count",
    "format_bytes",
    "format_count",
    "format_duration",
]
