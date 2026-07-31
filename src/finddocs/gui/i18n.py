"""Teksty interfejsu w jezyku polskim.

Wszystkie napisy widoczne dla uzytkownika sa w jednym miejscu. Ulatwia to korekte
jezykowa i pozniejsze dodanie innej wersji jezykowej bez szukania po widokach.
"""

from __future__ import annotations

from finddocs.types import DocumentStatus, JobState, MatchKind, SearchMode

APP_TITLE = "FindDocs"
APP_SUBTITLE = "Lokalna wyszukiwarka dokumentow"

# --- nawigacja ---------------------------------------------------------------

NAV_SEARCH = "Wyszukiwanie"
NAV_SOURCES = "Zrodla i konfiguracja"
NAV_INDEXING = "Indeksowanie"
NAV_REPORT = "Raport pokrycia"
NAV_DIAGNOSTICS = "Diagnostyka"

# --- ekran wyszukiwania ------------------------------------------------------

SEARCH_PLACEHOLDER = "Wpisz zapytanie, na przyklad: procedura przelewow z 24.07.2015"
SEARCH_BUTTON = "Szukaj"
SEARCH_CANCEL = "Przerwij"
SEARCH_FILTERS = "Filtry"
SEARCH_FILTERS_CLEAR = "Wyczysc filtry"
SEARCH_NO_RESULTS = "Brak wynikow dla tego zapytania."
SEARCH_EMPTY_STATE = (
    "Wpisz zapytanie i nacisnij Enter.\n\n"
    "Tryb Dokladne znajduje wszystkie dokumenty zawierajace podane slowa, numery i daty.\n"
    "Tryb Semantyczne szuka dokumentow powiazanych znaczeniowo.\n"
    "Tryb Hybrydowe laczy oba podejscia."
)
SEARCH_RUNNING = "Wyszukiwanie w toku..."
SEARCH_INDEX_EMPTY = (
    "Indeks jest pusty. Przejdz do ekranu Indeksowanie i uruchom skanowanie zrodla."
)

MODE_LABELS: dict[SearchMode, str] = {
    SearchMode.HYBRID: "Hybrydowe",
    SearchMode.EXACT: "Dokladne",
    SearchMode.SEMANTIC: "Semantyczne",
}

MODE_HINTS: dict[SearchMode, str] = {
    SearchMode.HYBRID: "Laczy dopasowania doslowne z podobienstwem znaczeniowym.",
    SearchMode.EXACT: "Zwraca wszystkie dokumenty zawierajace podane wartosci.",
    SearchMode.SEMANTIC: "Ranking przyblizony. Nie gwarantuje kompletnosci wynikow.",
}

MATCH_LABELS: dict[MatchKind, str] = {
    MatchKind.EXACT: "dopasowanie dokladne",
    MatchKind.SEMANTIC: "dopasowanie semantyczne",
    MatchKind.HYBRID: "dopasowanie hybrydowe",
}

RESULT_OPEN = "Otworz dokument"
RESULT_OPEN_LOCATION = "Otworz lokalizacje"
RESULT_COPY_LINK = "Kopiuj odnosnik"
RESULT_OCR_BADGE = "OCR"
RESULT_MORE_CHUNKS = "Pasujacych fragmentow w tym dokumencie: {count}"
RESULT_MODIFIED = "Zmodyfikowano: {value}"
RESULT_INDEXED = "Zaindeksowano: {value}"
RESULT_AUTHOR = "Autor: {value}"
RESULT_SCORE = "Sila dopasowania: {value}"
RESULT_SCORE_TOOLTIP = (
    "Wartosc wzgledna wobec najlepszego wyniku na tej stronie. "
    "Nie jest to prawdopodobienstwo ani miara bezwzgledna."
)

FILTER_EXTENSION = "Typ pliku"
FILTER_SOURCE = "Zrodlo"
FILTER_LIBRARY = "Biblioteka"
FILTER_AUTHOR = "Autor"
FILTER_PATH = "Katalog albo lokalizacja"
FILTER_DATE_FROM = "Data od"
FILTER_DATE_TO = "Data do"
FILTER_OCR = "Tylko dokumenty z OCR"
FILTER_ANY = "wszystkie"

PAGINATION_PREVIOUS = "Poprzednia"
PAGINATION_NEXT = "Nastepna"
PAGINATION_STATUS = "Strona {page} z {pages}"
RESULTS_COUNT_EXACT = "Znaleziono {count} dokumentow"
RESULTS_COUNT_APPROX = "Znaleziono co najmniej {count} dokumentow"
RESULTS_TOOK = "czas: {ms} ms"

# --- ekran zrodel ------------------------------------------------------------

SOURCES_TITLE = "Zrodla dokumentow"
SOURCES_ADD_LOCAL = "Dodaj katalog lokalny"
SOURCES_ADD_SHAREPOINT = "Dodaj SharePoint"
SOURCES_TEST = "Testuj polaczenie"
SOURCES_REMOVE = "Usun zrodlo"
SOURCES_TOGGLE = "Wlacz albo wylacz"
SOURCES_EMPTY = "Nie skonfigurowano zadnego zrodla."
SOURCES_DEMO = "Wygeneruj zbior demonstracyjny"
SOURCES_SIGN_IN = "Zaloguj do SharePoint"
SOURCES_SIGN_OUT = "Wyloguj"

STORAGE_TITLE = "Przechowywanie indeksu"
STORAGE_PATH = "Katalog danych"
STORAGE_CHANGE = "Zmien katalog"
STORAGE_FREE = "Wolne miejsce: {value}"
STORAGE_INDEX_SIZE = "Rozmiar indeksu: {value}"

MODEL_TITLE = "Model wyszukiwania semantycznego"
MODEL_CURRENT = "Model: {value}"
MODEL_DIMENSION = "Wymiar wektora: {value}"
MODEL_MISSING = (
    "Model nie zostal znaleziony. Wyszukiwanie semantyczne i hybrydowe sa niedostepne, "
    "tryb dokladny dziala normalnie."
)

# --- ekran indeksowania ------------------------------------------------------

INDEXING_TITLE = "Indeksowanie"
INDEXING_START = "Start"
INDEXING_PAUSE = "Pauza"
INDEXING_RESUME = "Wznow"
INDEXING_CANCEL = "Anuluj"
INDEXING_RESCAN = "Skanuj ponownie"
INDEXING_FULL = "Pelne przeindeksowanie"
INDEXING_EXPORT = "Eksportuj raport"
INDEXING_SHOW_ERRORS = "Pokaz bledy"
INDEXING_SHOW_SKIPPED = "Pokaz pliki pominiete"

STAGE_LABEL = "Etap"
STAT_DISCOVERED = "Wykryte pliki"
STAT_PROCESSED = "Przetworzone"
STAT_UNCHANGED = "Niezmienione"
STAT_SKIPPED = "Pominiete"
STAT_FAILED = "Bledy"
STAT_DELETED = "Usuniete ze zrodla"
STAT_OCR = "Pliki z OCR"
STAT_OCR_PAGES = "Strony OCR"
STAT_CURRENT = "Przetwarzany plik"
STAT_ELAPSED = "Czas trwania"
STAT_CONNECTION = "Polaczenie"
STAT_TEMP = "Przestrzen tymczasowa"
PROGRESS_UNKNOWN = "Postep bedzie znany po zakonczeniu wykrywania plikow"
PROGRESS_APPROXIMATE = "Postep przyblizony: {value}"

JOB_STATE_LABELS: dict[JobState, str] = {
    JobState.QUEUED: "w kolejce",
    JobState.RUNNING: "w toku",
    JobState.PAUSED: "wstrzymane",
    JobState.CANCELLING: "anulowanie",
    JobState.CANCELLED: "anulowane",
    JobState.FAILED: "zakonczone bledem",
    JobState.COMPLETED: "zakonczone",
}

RESUME_PROMPT = (
    "Poprzednie indeksowanie zostalo przerwane. Czy chcesz je wznowic?\n"
    "Dokumenty juz przetworzone nie beda przetwarzane ponownie."
)
RESUME_TITLE = "Przerwane indeksowanie"

# --- raport ------------------------------------------------------------------

REPORT_TITLE = "Raport pokrycia"
REPORT_EXPORT_JSON = "Eksportuj do JSON"
REPORT_EXPORT_CSV = "Eksportuj do CSV"
REPORT_REFRESH = "Odswiez"
REPORT_NON_SEARCHABLE = "Dokumenty, ktorych nie mozna wyszukac"
REPORT_COMPLETE = "Wszystkie wykryte dokumenty sa wyszukiwalne."
REPORT_INCOMPLETE = (
    "Zbior nie jest kompletny. Nie mozna wyszukac {count} dokumentow. "
    "Szczegoly znajduja sie na liscie ponizej."
)

# --- diagnostyka -------------------------------------------------------------

DIAG_TITLE = "Diagnostyka"
DIAG_ENVIRONMENT = "Srodowisko"
DIAG_COMPONENTS = "Komponenty"
DIAG_INDEX = "Indeks"
DIAG_CONSISTENCY = "Spojnosc indeksu"
DIAG_NETWORK = "Polityka polaczen sieciowych"
DIAG_EXPORT_BUNDLE = "Eksportuj pakiet diagnostyczny"
DIAG_OPEN_LOGS = "Otworz katalog logow"
DIAG_CHECK = "Sprawdz spojnosc"
DIAG_COMPACT = "Kompaktuj indeks wektorowy"
DIAG_BACKUP = "Wykonaj kopie indeksu"
DIAG_LOG_QUERIES = "Zapisuj zapytania w logu diagnostycznym"
DIAG_LOG_QUERIES_HINT = (
    "Domyslnie wylaczone. Wlacz tylko na czas diagnozy. Zapytania zostana zapisane "
    "wylacznie w lokalnym pliku logu."
)

# --- statusy dokumentow ------------------------------------------------------

STATUS_LABELS: dict[DocumentStatus, str] = {
    DocumentStatus.PENDING: "oczekuje",
    DocumentStatus.INDEXED: "zaindeksowany",
    DocumentStatus.PARTIAL: "zaindeksowany czesciowo",
    DocumentStatus.SKIPPED: "pominiety",
    DocumentStatus.UNSUPPORTED: "format nieobslugiwany",
    DocumentStatus.CORRUPTED: "plik uszkodzony",
    DocumentStatus.PASSWORD_PROTECTED: "zabezpieczony haslem",
    DocumentStatus.EMPTY: "brak tresci",
    DocumentStatus.DOWNLOAD_FAILED: "blad pobierania",
    DocumentStatus.ERROR: "blad przetwarzania",
    DocumentStatus.DELETED: "usuniety ze zrodla",
}

# --- komunikaty ogolne -------------------------------------------------------

BUTTON_OK = "OK"
BUTTON_CANCEL = "Anuluj"
BUTTON_CLOSE = "Zamknij"
BUTTON_SAVE = "Zapisz"
BUTTON_BROWSE = "Przegladaj..."

ERROR_TITLE = "Wystapil blad"
WARNING_TITLE = "Ostrzezenie"
INFO_TITLE = "Informacja"
CONFIRM_TITLE = "Potwierdzenie"

CONFIRM_REMOVE_SOURCE = (
    "Czy na pewno usunac zrodlo '{label}'?\nDokumenty z tego zrodla zostana usuniete z indeksu."
)
CONFIRM_FULL_REINDEX = (
    "Pelne przeindeksowanie przetworzy wszystkie dokumenty od nowa. "
    "Moze to potrwac dlugo. Kontynuowac?"
)

STARTUP_ERROR = (
    "Nie udalo sie uruchomic aplikacji.\n\n{message}\n\nSzczegoly zapisano w pliku logu:\n{log}"
)

INDEX_INCOMPATIBLE_TITLE = "Indeks wymaga przebudowy"
INDEX_INCOMPATIBLE = (
    "Konfiguracja aplikacji zmienila sie od czasu zbudowania indeksu.\n\n{details}\n\n"
    "Do czasu przebudowy dostepne jest wyszukiwanie dokladne."
)

STARTUP_NOTES_TITLE = "Stan indeksu"
STARTUP_NOTES = (
    "Aplikacja jest gotowa do pracy, ale nie wszystkie funkcje sa dostepne.\n\n{details}"
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
    return format_count(count, "dokument", "dokumenty", "dokumentow")


def files_count(count: int) -> str:
    return format_count(count, "plik", "pliki", "plikow")


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
