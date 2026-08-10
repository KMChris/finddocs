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
NAV_SETTINGS = "Ustawienia"

# --- ekran ustawien ----------------------------------------------------------

SETTINGS_APPEARANCE = "Wygląd"
SETTINGS_THEME = "Motyw"
THEME_LABELS: dict[str, str] = {"system": "Systemowy", "light": "Jasny", "dark": "Ciemny"}
SETTINGS_THEME_HINT = "Zmiana motywu działa od razu i jest zapamiętywana."
SETTINGS_BEHAVIOR = "Zachowanie"
SETTINGS_OPEN_WITH = "Otwieranie dokumentów"
SETTINGS_OPEN_WEB = "W SharePoint, w przeglądarce"
SETTINGS_OPEN_LOCAL = "Kopia lokalna, gdy jest dostępna"
SETTINGS_PAGE_SIZE = "Wyników na stronę"
SETTINGS_SHOW_SCORES = "Pokazuj plakietkę siły dopasowania"
SETTINGS_SAVED = "Zapisano ustawienia."
ABOUT_TITLE = "O programie"
ABOUT_DATA_DIR = "Katalog danych"
ABOUT_LOGS_DIR = "Katalog logów"
ABOUT_OPEN_DATA = "Otwórz katalog danych"
ABOUT_OPEN_LOGS = "Otwórz katalog logów"

# --- ekran wyszukiwania ------------------------------------------------------

SEARCH_PLACEHOLDER = "Wpisz zapytanie, na przykład: procedura przelewów z 24.07.2015"
SEARCH_BUTTON = "Szukaj"
SEARCH_CANCEL = "Przerwij"
SEARCH_FILTERS = "Filtry"
SEARCH_FILTERS_ACTIVE = "Filtry ({count})"
SEARCH_FILTERS_CLEAR = "Wyczyść filtry"
SEARCH_FILTERS_SHORTCUT = "Pokaż albo ukryj panel filtrów (Ctrl+Shift+F)"
SEARCH_NO_RESULTS_TITLE = "Brak wyników"
SEARCH_NO_RESULTS = (
    "Żaden dokument nie odpowiada temu zapytaniu. Spróbuj krótszego zapytania, "
    "zmień tryb na Semantyczne albo wyczyść filtry."
)
SEARCH_EMPTY_TITLE = "Zacznij od zapytania"
SEARCH_EMPTY_STATE = (
    "Tryb Dokładne znajduje wszystkie dokumenty zawierające podane słowa, numery i daty.\n"
    "Tryb Semantyczne szuka dokumentów powiązanych znaczeniowo.\n"
    "Tryb Hybrydowe łączy oba podejścia."
)
SEARCH_RUNNING = "Wyszukiwanie w toku..."
SEARCH_INDEX_EMPTY_TITLE = "Indeks jest pusty"
SEARCH_INDEX_EMPTY = "Przejdź do ekranu Indeksowanie i uruchom skanowanie źródła."

MODE_LABELS: dict[SearchMode, str] = {
    SearchMode.HYBRID: "Hybrydowe",
    SearchMode.EXACT: "Dokładne",
    SearchMode.SEMANTIC: "Semantyczne",
}

MODE_HINTS: dict[SearchMode, str] = {
    SearchMode.HYBRID: (
        "Łączy dopasowania dosłowne z podobieństwem znaczeniowym. "
        "Pełną listę dopasowań dosłownych daje tryb Dokładne."
    ),
    SearchMode.EXACT: "Zwraca wszystkie dokumenty zawierające podane wartości.",
    SearchMode.SEMANTIC: "Ranking przybliżony. Nie gwarantuje kompletności wyników.",
}

# Plakietka rodzaju dopasowania jest widoczna tylko w trybie hybrydowym,
# gdzie rodzaj faktycznie rozni sie miedzy wynikami. Sam przymiotnik wystarcza,
# bo obok jest plakietka sily zaczynajaca sie od slowa ,,dopasowanie''.
MATCH_LABELS: dict[MatchKind, str] = {
    MatchKind.EXACT: "dokładne",
    MatchKind.SEMANTIC: "semantyczne",
    MatchKind.HYBRID: "hybrydowe",
}

RESULT_OPEN = "Otwórz dokument"
RESULT_OPEN_HINT = "Otwórz dokument (Enter)"
RESULT_OPEN_LOCATION = "Otwórz lokalizację"
RESULT_COPY_LINK = "Kopiuj odnośnik"
RESULT_OCR_BADGE = "OCR"
RESULT_MORE_CHUNKS = "Pasujących fragmentów w tym dokumencie: {count}"
RESULT_SHOW_MORE = "Pokaż więcej fragmentów ({count})"
RESULT_SHOW_MORE_HINT = "Pokaż pozostałe pobrane fragmenty tego dokumentu"
RESULT_MODIFIED = "Zmodyfikowano: {value}"
RESULT_INDEXED = "Zaindeksowano: {value}"
RESULT_AUTHOR = "Autor: {value}"
RESULT_SCORE = "Siła dopasowania: {value}"

# Plakietki na karcie wyniku niosa krotki napis, a pelne zdanie jest
# w podpowiedzi. Cztery pelne zdania obok siebie zaslanialy tresc fragmentu.
BADGE_MATCH_TOOLTIP = "Skąd pochodzi trafienie: część dokładna, semantyczna albo obie"
BADGE_TYPE_TOOLTIP = "Typ pliku"
BADGE_MODIFIED_TOOLTIP = "Data modyfikacji dokumentu"
BADGE_AUTHOR_TOOLTIP = "Autor z metadanych dokumentu"
BADGE_OCR_TOOLTIP = "Tekst rozpoznany z obrazu, wraz z jakością rozpoznania"
RESULT_SCORE_SHORT = "dopasowanie {value}"
RESULT_SCORE_TOOLTIP = (
    "Siła dopasowania. Wartość względna wobec najlepszego wyniku na tej stronie. "
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
PAGINATION_PREVIOUS_HINT = "Poprzednia strona wyników (Alt+Left)"
PAGINATION_NEXT_HINT = "Następna strona wyników (Alt+Right)"
PAGINATION_STATUS = "Strona {page} z {pages}"
#: Liczbe dokumentow wstawia ``documents_count``, zeby odmiana byla poprawna
#: takze dla jednego i dla dwoch dokumentow.
RESULTS_COUNT_EXACT = "Znaleziono {count}"
RESULTS_COUNT_APPROX = "Znaleziono co najmniej {count}"
RESULTS_TOOK = "czas: {ms} ms"

# --- ekran zrodel ------------------------------------------------------------

SOURCES_TITLE = "Źródła dokumentów"
# Napisy na przyciskach sa krotkie, bo caly wiersz musi sie zmiescic takze
# w oknie o najmniejszym dozwolonym rozmiarze. Pelne zdanie jest w podpowiedzi.
SOURCES_ADD_LOCAL = "Dodaj katalog"
SOURCES_ADD_LOCAL_HINT = "Dodaj katalog lokalny albo zasób sieciowy jako źródło dokumentów"
SOURCES_ADD_SHAREPOINT = "Dodaj SharePoint"
SOURCES_ADD_SHAREPOINT_HINT = "Dodaj bibliotekę dokumentów SharePoint przez Microsoft Graph"
SOURCES_TEST = "Testuj połączenie"
SOURCES_TEST_HINT = "Sprawdź, czy wybrane źródło jest dostępne"
SOURCES_REMOVE = "Usuń"
SOURCES_REMOVE_HINT = "Usuń wybrane źródło z konfiguracji oraz jego dokumenty z indeksu"
SOURCES_ENABLED_ON = "Włączono źródło {label}."
SOURCES_ENABLED_OFF = "Wyłączono źródło {label}. Jego dokumenty zostają w indeksie."
SOURCES_ACTIVE_HINT = "Zaznaczone źródło bierze udział w skanowaniu i wyszukiwaniu"
SOURCES_EMPTY = "Nie skonfigurowano żadnego źródła."
SOURCES_EMPTY_HINT = (
    "Nie skonfigurowano żadnego źródła. Dodaj katalog lokalny albo bibliotekę SharePoint. "
    "Przycisk „Zbiór demonstracyjny” tworzy kilkanaście przykładowych dokumentów, "
    "na których można sprawdzić działanie aplikacji."
)
SOURCES_DEMO = "Utwórz zbiór demonstracyjny"
SOURCES_DEMO_HINT = "Utwórz katalog z przykładowymi polskimi dokumentami i dodaj go jako źródło"
SOURCES_SELECT_FIRST = "Wybierz źródło z listy."
SOURCES_SIGN_IN = "Zaloguj do SharePoint"
SOURCES_SIGN_OUT = "Wyloguj"

STORAGE_TITLE = "Przechowywanie indeksu"
STORAGE_PATH = "Katalog danych"
STORAGE_CHANGE = "Zmień katalog"
STORAGE_OPEN = "Otwórz katalog"
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
#: Jeden przycisk zamiast dawnych ,,Start'' i ,,Skanuj ponownie''. Oba zlecaly
#: to samo zadanie, wiec obok siebie sugerowaly dwie rozne operacje.
INDEXING_SCAN = "Skanuj źródła"
INDEXING_SCAN_HINT = (
    "Dodaje nowe pliki, aktualizuje zmienione i usuwa z indeksu te, których już nie ma w źródle."
)
INDEXING_PAUSE = "Pauza"
INDEXING_RESUME = "Wznów"
INDEXING_CANCEL = "Anuluj"
INDEXING_CANCEL_HINT = "Przerywa zadanie. Indeks pozostaje spójny, pracę można wznowić później."
INDEXING_FULL = "Pełne przeindeksowanie"
INDEXING_FULL_HINT = "Przetwarza wszystkie dokumenty od nowa, także te, które się nie zmieniły."
INDEXING_EXPORT = "Eksportuj raport"
INDEXING_TAB_ERRORS = "Błędy"
INDEXING_TAB_SKIPPED = "Pliki pominięte"
#: Nazwa zakladki z liczba wierszy. Bez liczby trzeba kliknac, zeby sprawdzic,
#: czy w ogole jest tam cos do ogladania.
INDEXING_TAB_COUNT = "{name} ({count})"
INDEXING_IDLE = "Gotowe do uruchomienia"

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
STAT_NONE = "brak"
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

# Klucze to surowe wartosci kolumny kind z historii zadan.
JOB_KIND_LABELS: dict[str, str] = {
    "rescan": "Skanowanie źródeł",
    "full_index": "Pełne przeindeksowanie",
    "rebuild_vectors": "Przebudowa indeksu wektorowego",
}

# Nazwy etapow z logu bledow. Wartosci spoza slownika przechodza bez zmian.
STAGE_LABELS: dict[str, str] = {
    "attachment": "załącznik",
    "chunk": "fragmentacja",
    "download": "pobieranie",
    "extract": "ekstrakcja",
    "pipeline": "przetwarzanie",
    "process": "przetwarzanie",
    "scan": "skanowanie",
    "warning": "ostrzeżenie",
}

TABLE_FILTER_PLACEHOLDER = "Filtruj wiersze..."

INDEXING_LAST_RUN = "Ostatni przebieg"
INDEXING_LAST_RUN_SUMMARY = (
    "Przetworzone: {processed}, błędy: {failed}, pominięte: {skipped}, czas: {elapsed}"
)
STAT_FAILED_HINT = "Kliknij, żeby otworzyć listę błędów"

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
REPORT_SUMMARY = "Pokrycie"
REPORT_TECH = "Informacje techniczne"
REPORT_NON_SEARCHABLE = "Dokumenty, których nie można wyszukać"
REPORT_COMPLETE = "Wszystkie wykryte dokumenty są wyszukiwalne."
REPORT_INCOMPLETE = (
    "Zbiór nie jest kompletny. Nie można wyszukać {count}. "
    "Szczegóły znajdują się na liście poniżej."
)
REPORT_EMPTY = "Indeks jest pusty. Uruchom skanowanie na ekranie Indeksowanie."
REPORT_STAMP = "Stan z {time}"
REPORT_NEEDS_REFRESH = "Raport jest przeliczany..."

# --- diagnostyka -------------------------------------------------------------

DIAG_TITLE = "Diagnostyka"
DIAG_ENVIRONMENT = "Środowisko"
DIAG_COMPONENTS = "Komponenty"
DIAG_INDEX = "Indeks"
DIAG_CONSISTENCY = "Spójność indeksu"
DIAG_NETWORK = "Polityka połączeń sieciowych"
DIAG_REFRESH = "Odśwież"
# Krotkie napisy na przyciskach, pelne zdanie w podpowiedzi: caly wiersz
# szesciu akcji musi sie zmiescic takze w najwezszym dozwolonym oknie.
DIAG_EXPORT_BUNDLE = "Pakiet diagnostyczny"
DIAG_EXPORT_BUNDLE_HINT = (
    "Zapisz archiwum z konfiguracją, logami i statystykami. Pakiet nie zawiera treści dokumentów."
)
DIAG_OPEN_LOGS = "Katalog logów"
DIAG_OPEN_LOGS_HINT = "Otwórz katalog z plikami logów w Eksploratorze plików"
DIAG_CHECK = "Sprawdź spójność"
DIAG_CHECK_HINT = "Porównaj metadane, indeks pełnotekstowy i indeks wektorowy"
DIAG_COMPACT = "Kompaktuj wektory"
DIAG_COMPACT_HINT = "Usuń z indeksu wektorowego wpisy po skasowanych dokumentach"
DIAG_BACKUP = "Kopia indeksu"
DIAG_BACKUP_HINT = "Zapisz kopię plików indeksu w katalogu kopii zapasowych"
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

#: Pasek stanu okna glownego.
STATUS_SEPARATOR = "   |   "
STATUS_INDEX_UNAVAILABLE = "Indeks niedostępny"
STATUS_SEMANTIC_DISABLED = "Tryb semantyczny wyłączony"
STATUS_SEMANTIC_UNAVAILABLE = "Tryb semantyczny niedostępny"

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
