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
NAV_SETTINGS = "Ustawienia"

# --- ekran ustawien ----------------------------------------------------------

SETTINGS_TAB_GENERAL = "Ogólne"
SETTINGS_APPEARANCE = "Wygląd"
SETTINGS_THEME = "Motyw"
THEME_LABELS: dict[str, str] = {"system": "Systemowy", "light": "Jasny", "dark": "Ciemny"}
SETTINGS_THEME_HINT = "Zmiana motywu działa od razu i jest zapamiętywana."
SETTINGS_MICA = "Tło Mica okna (Windows 11)"
SETTINGS_MICA_HINT = "Przezroczysty materiał systemowy pod oknem. Zmiana przebudowuje okno."
SETTINGS_BEHAVIOR = "Zachowanie"
SETTINGS_OPEN_WITH = "Otwieranie dokumentów"
SETTINGS_OPEN_WEB = "W SharePoint, w przeglądarce"
SETTINGS_OPEN_LOCAL = "Kopia lokalna, gdy jest dostępna"
SETTINGS_PAGE_SIZE = "Wyników na stronę"
SETTINGS_SHOW_SCORES = "Pokazuj plakietkę siły dopasowania"
SETTINGS_INCREMENTAL = "Wyszukiwanie przyrostowe w trybie Dokładne"
SETTINGS_INCREMENTAL_HINT = (
    "Wyniki pojawiają się w trakcie pisania. Działa dla indeksów do 50 tysięcy dokumentów."
)
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
WELCOME_TITLE = "Witaj w FindDocs"
WELCOME_TEXT = (
    "Nie ma jeszcze żadnego źródła dokumentów.\n"
    "Dodaj katalog albo utwórz zbiór demonstracyjny, a potem uruchom skanowanie."
)
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
RESULT_CONTEXT = "Pokaż kontekst trafienia"
RESULT_CONTEXT_HINT = "Dokleja sąsiednie fragmenty dokumentu z indeksu, bez otwierania pliku"
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
FILTER_CHIP_HINT = "Usuń ten filtr"
FILTER_DATE_FROM_CHIP = "od {date}"
FILTER_DATE_TO_CHIP = "do {date}"

SORT_RELEVANCE = "Trafność"
SORT_NEWEST = "Najnowsze"
SORT_HINT = "Porządek wyników. Sortowanie po dacie działa w trybie Dokładne."

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

# Ekran dzieli sie na trzy zakladki: zrodla dokumentow, konfiguracja
# wyszukiwania semantycznego oraz przechowywanie danych indeksu.
SOURCES_TAB_SOURCES = "Źródła"
SOURCES_TAB_SEMANTIC = "Wyszukiwanie semantyczne"
SOURCES_TAB_STORAGE = "Przechowywanie"

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

SOURCES_OPTIONS_TITLE = "Opcje indeksowania"
SOURCES_INDEX_ARCHIVES = "Indeksuj zawartość archiwów ZIP"
SOURCES_INDEX_ARCHIVES_HINT = (
    "Po włączeniu archiwum jest rozpakowywane, a każdy plik w środku trafia do indeksu "
    "jako osobny dokument, tak jak załącznik wiadomości. Zmiana zaczyna działać "
    "od następnego skanowania."
)
SOURCES_INDEX_ARCHIVES_ON = "Włączono indeksowanie zawartości archiwów ZIP."
SOURCES_INDEX_ARCHIVES_OFF = "Wyłączono indeksowanie zawartości archiwów ZIP."
SOURCES_SELECT_FIRST = "Wybierz źródło z listy."
SOURCES_SIGN_IN = "Zaloguj do SharePoint"
SOURCES_SIGN_OUT = "Wyloguj"

STORAGE_TITLE = "Przechowywanie indeksu"
STORAGE_PATH = "Katalog danych"
STORAGE_CHANGE = "Zmień katalog"
STORAGE_OPEN = "Otwórz katalog"
STORAGE_FREE = "Wolne miejsce: {value}"
STORAGE_INDEX_SIZE = "Rozmiar indeksu: {value}"

MODEL_CURRENT = "Model: {value}"
MODEL_DIMENSION = "Wymiar wektora: {value}"
MODEL_MISSING = (
    "Model nie został znaleziony. Wyszukiwanie semantyczne i hybrydowe są niedostępne, "
    "tryb dokładny działa normalnie."
)
MODEL_SEMANTIC_DISABLED = (
    "Indeksowanie semantyczne jest wyłączone w ustawieniach. Tryb dokładny działa normalnie."
)

# --- karty konfiguracji wyszukiwania semantycznego ----------------------------

MODEL_SEMANTIC_BOX = "Wyszukiwanie semantyczne"
MODEL_BOX = "Model embeddingów"
MODEL_COMBO_LABEL = "Model"
MODEL_QUANTIZED = "Użyj wersji skwantyzowanej (szybsza, mniejszy plik)"
MODEL_QUERY_PREFIX = "Przedrostek zapytania"
MODEL_PASSAGE_PREFIX = "Przedrostek treści"
MODEL_PREFIX_HINT = (
    "Przedrostki są doklejane do tekstu przed policzeniem wektora. Model MMLW "
    "wymaga przedrostka „zapytanie: ” wyłącznie dla zapytań, rodzina E5 "
    "wymaga „query: ” i „passage: ”. Zmiana przedrostków wymaga "
    "przebudowy części semantycznej indeksu."
)
MODEL_SEMANTIC_TOGGLE = "Włącz indeksowanie i wyszukiwanie semantyczne"
MODEL_SEMANTIC_HINT = (
    "Po wyłączeniu nowe dokumenty są indeksowane tylko pełnotekstowo, a tryby "
    "semantyczny i hybrydowy przestają działać. Po ponownym włączeniu wystarczy "
    "zwykłe skanowanie: brakujące wektory zostaną uzupełnione automatycznie."
)
MODEL_CONTEXT_TOGGLE = "Wzbogacaj wektory o nazwę pliku i ścieżkę"
MODEL_CONTEXT_HINT = (
    "Przed policzeniem wektora każdy fragment dostaje nagłówek z nazwą pliku "
    "i jego ścieżką w źródle. Zapytania wspominające katalog albo nazwę pliku "
    "znajdą dokument, nawet gdy jego treść o nich nie wspomina. Nagłówek nie "
    "trafia do indeksu pełnotekstowego. Zmiana tej opcji wymaga przebudowy "
    "części semantycznej indeksu."
)
MODEL_PROFILE_BOX = "Profile dostawcy embeddingów"
MODEL_PROFILE_LABEL = "Profil"
MODEL_PROFILE_ACTIVE = "Aktywny profil: {value}"
MODEL_PROFILE_NONE = "brak (ustawienia własne)"
MODEL_PROFILE_ACTIVATE = "Aktywuj"
MODEL_PROFILE_SAVE_AS = "Zapisz bieżące jako profil"
MODEL_PROFILE_REMOVE = "Usuń"
MODEL_PROFILE_NAME_PROMPT = "Nazwa profilu:"
MODEL_PROFILE_NAME_EMPTY = "Nazwa profilu nie może być pusta."
MODEL_PROFILE_OVERWRITE = "Profil „{name}” już istnieje. Zastąpić go bieżącymi ustawieniami?"
MODEL_PROFILE_ALREADY_ACTIVE = "Profil „{name}” jest już aktywny."
MODEL_PROFILE_ACTIVATED = "Aktywowano profil „{name}”."
MODEL_PROFILE_SAVED = "Zapisano profil „{name}”."
MODEL_PROFILE_REMOVED = "Usunięto profil „{name}”."
MODEL_PROFILE_REMOVE_ACTIVE = "Nie można usunąć aktywnego profilu. Najpierw aktywuj inny profil."
MODEL_PROFILE_REMOVE_CONFIRM = "Usunąć profil „{name}”? Zapisane w nim ustawienia przepadną."
MODEL_PROFILE_TYPE_LOCAL = "model lokalny: {value}"
MODEL_PROFILE_TYPE_REMOTE = "zdalne API: {value}"
MODEL_PROFILE_HINT = (
    "Profil to nazwany zestaw ustawień dostawcy embeddingów: model lokalny "
    "z urządzeniem obliczeń albo zdalne API z adresem i kontraktem. Aktywacja "
    "profilu przełącza całą konfigurację. Zmiana ustawień na kartach niżej "
    "nie nadpisuje profilu: znika wtedy tylko wskazanie profilu aktywnego, "
    "a nowe ustawienia można zapisać jako profil ponownie. Przełączenie na "
    "profil o innym modelu lub wymiarze unieważnia część semantyczną indeksu "
    "i wymaga jej przebudowy; do tego czasu działa wyszukiwanie dokładne."
)
MODEL_COMPUTE_BOX = "Obliczenia embeddingów"
MODEL_PROVIDER_LABEL = "Dostawca embeddingów"
MODEL_PROVIDER_LOCAL = "Model lokalny (ONNX)"
MODEL_PROVIDER_LOCAL_HINT = "Embeddingi są liczone na tym komputerze, bez połączeń sieciowych"
MODEL_PROVIDER_REMOTE = "Zdalne API organizacji"
MODEL_PROVIDER_REMOTE_HINT = (
    "Embeddingi liczy API wskazane przez organizację. Treść fragmentów opuszcza ten komputer"
)
MODEL_DEVICE_LABEL = "Urządzenie"
MODEL_DEVICE_CPU = "Procesor (CPU)"
MODEL_DEVICE_AUTO = "Automatycznie (GPU, gdy dostępne)"
MODEL_DEVICE_DML = "Karta graficzna (DirectML)"
MODEL_DEVICE_CUDA = "Karta graficzna (CUDA)"
MODEL_DEVICE_AVAILABLE = "Dostępne w tym środowisku: {value}"
MODEL_DEVICE_HINT = (
    "Obliczenia na karcie graficznej wymagają wariantu GPU pakietu onnxruntime, "
    "instalowanego dodatkiem finddocs[gpu-cuda] (karty NVIDIA, najszybszy zmierzony "
    "wariant) albo finddocs[gpu-dml] (DirectML, dowolna karta na Windows); opis "
    "w instrukcji administratora. Na karcie graficznej najszybszy jest pełny model "
    "FP32, wariant INT8 zostaw procesorowi. Gdy wybranego urządzenia nie ma "
    "w środowisku, obliczenia wracają na procesor. Zmiana samego urządzenia nie "
    "wymaga przebudowy indeksu."
)
MODEL_BATCH_LABEL = "Fragmenty w jednym przebiegu modelu"
MODEL_BATCH_DOCS_LABEL = "Dokumenty osadzane wspólnie"
MODEL_BATCH_DOCS_HINT = (
    "Podczas indeksowania fragmenty kolejnych dokumentów są zbierane i osadzane "
    "jednym wywołaniem modelu. Wartość 1 wyłącza wspólne osadzanie."
)
MODEL_REMOTE_URL = "Adres API"
MODEL_REMOTE_URL_PLACEHOLDER = "https://api.example.com/v1"
MODEL_REMOTE_PROTOCOL = "Kontrakt"
MODEL_REMOTE_PROTOCOL_OPENAI = "Zgodny z OpenAI (domyślny)"
MODEL_REMOTE_PROTOCOL_FINDDOCS = "Rozszerzony o pole kind (FindDocs)"
MODEL_REMOTE_PREFIX_HINT = (
    "Przy kontrakcie OpenAI aplikacja dokleja przedrostki do tekstów przed "
    "wysyłką; wpisz je, jeżeli model po stronie API ich wymaga. Przy kontrakcie "
    "rozszerzonym serwer sam rozpoznaje rodzaj tekstu po polu kind, więc "
    "przedrostki zwykle zostają puste."
)
MODEL_REMOTE_MODEL = "Nazwa modelu"
MODEL_REMOTE_DIMENSION = "Wymiar wektora"
MODEL_REMOTE_BATCH = "Teksty w jednym żądaniu"
MODEL_REMOTE_KEY = "Klucz API"
MODEL_REMOTE_KEY_PLACEHOLDER = "wklej klucz, aby go zapisać"
MODEL_REMOTE_KEY_SAVE = "Zapisz klucz"
MODEL_REMOTE_KEY_CLEAR = "Usuń klucz"
MODEL_REMOTE_KEY_SAVED = "Klucz API został zapisany w magazynie poświadczeń."
MODEL_REMOTE_KEY_CLEARED = "Klucz API został usunięty z magazynu poświadczeń."
MODEL_REMOTE_KEY_PRESENT = "Klucz: zapisany w magazynie poświadczeń"
MODEL_REMOTE_KEY_MISSING = "Klucz: brak"
MODEL_REMOTE_KEY_EMPTY = "Wklej klucz w pole powyżej, zanim go zapiszesz."
MODEL_REMOTE_HINT = (
    "Treść fragmentów dokumentów będzie wysyłana na wskazany adres w celu policzenia "
    "embeddingów. Włączaj wyłącznie dla API zaakceptowanego przez organizację. "
    "Połączenia są ograniczone do hosta z podanego adresu i wyłącznie przez https."
)
MODEL_REMOTE_URL_REQUIRED = "Podaj adres zdalnego API, zanim je włączysz."
MODEL_VECTOR_BOX = "Magazyn wektorów"
MODEL_VECTOR_BACKEND = "Rodzaj magazynu"
MODEL_VECTOR_BACKEND_FAISS = "Plik lokalny (FAISS)"
MODEL_VECTOR_BACKEND_PGVECTOR = "Baza PostgreSQL (pgvector)"
MODEL_VECTOR_HOST = "Serwer"
MODEL_VECTOR_HOST_PLACEHOLDER = "np. baza.firma.local"
MODEL_VECTOR_PORT = "Port"
MODEL_VECTOR_DATABASE = "Baza danych"
MODEL_VECTOR_USER = "Użytkownik"
MODEL_VECTOR_SCHEMA = "Schemat"
MODEL_VECTOR_TABLE = "Tabela"
MODEL_VECTOR_SSLMODE = "Szyfrowanie (sslmode)"
MODEL_VECTOR_SSL_REQUIRE = "require (TLS wymagany)"
MODEL_VECTOR_SSL_VERIFY_CA = "verify-ca (TLS i weryfikacja CA)"
MODEL_VECTOR_SSL_VERIFY_FULL = "verify-full (TLS i weryfikacja hosta)"
MODEL_VECTOR_SSL_DISABLE = "disable (tylko localhost)"
MODEL_VECTOR_PASSWORD = "Hasło"
MODEL_VECTOR_PASSWORD_PLACEHOLDER = "wpisz hasło, aby je zapisać"
MODEL_VECTOR_PASSWORD_SAVE = "Zapisz hasło"
MODEL_VECTOR_PASSWORD_CLEAR = "Usuń hasło"
MODEL_VECTOR_PASSWORD_SAVED = "Hasło do bazy zostało zapisane w magazynie poświadczeń."
MODEL_VECTOR_PASSWORD_CLEARED = "Hasło do bazy zostało usunięte z magazynu poświadczeń."
MODEL_VECTOR_PASSWORD_PRESENT = "Hasło: zapisane w magazynie poświadczeń"
MODEL_VECTOR_PASSWORD_MISSING = "Hasło: brak"
MODEL_VECTOR_PASSWORD_EMPTY = "Wpisz hasło w pole powyżej, zanim je zapiszesz."
MODEL_VECTOR_TEST = "Przetestuj połączenie"
MODEL_VECTOR_TEST_RUNNING = "Trwa próba połączenia z bazą..."
MODEL_VECTOR_TEST_OK = (
    "Połączenie działa. Serwer PostgreSQL {version}, rozszerzenie pgvector {extension}."
)
MODEL_VECTOR_TEST_NO_EXTENSION = (
    "Połączenie działa, ale baza nie ma rozszerzenia pgvector. Poproś administratora "
    "bazy o wykonanie polecenia CREATE EXTENSION vector."
)
MODEL_VECTOR_FIELDS_REQUIRED = (
    "Podaj serwer, bazę danych i użytkownika, zanim włączysz magazyn pgvector."
)
MODEL_VECTOR_HINT = (
    "Wektory fragmentów mogą być przechowywane w bazie PostgreSQL z rozszerzeniem "
    "pgvector zamiast w pliku lokalnym. Do bazy trafiają wyłącznie wektory liczbowe "
    "i identyfikatory fragmentów, nigdy tekst dokumentów. Indeks pełnotekstowy "
    "i metadane pozostają na tym komputerze. Połączenia są ograniczone do podanego "
    "serwera, a poza localhost wymagany jest TLS. Zmiana magazynu wymaga przebudowy "
    "części semantycznej indeksu."
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

# --- diagnostyka (zakladka ekranu Ustawienia) --------------------------------

DIAG_TITLE = "Diagnostyka"
DIAG_ENVIRONMENT = "Środowisko"
DIAG_COMPONENTS = "Komponenty"
DIAG_INDEX = "Indeks"
# Krotka nazwa: obok sa jeszcze trzy zakladki i pole filtra, a caly wiersz
# musi sie zmiescic takze w najwezszym dozwolonym oknie.
DIAG_CONSISTENCY = "Spójność"
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

# --- dostepnosc --------------------------------------------------------------

#: Nazwy dla czytnikow ekranu tam, gdzie kontrolka nie ma wlasnego napisu.
A11Y_NAV = "Nawigacja główna"
A11Y_QUERY = "Pole zapytania"
A11Y_SORT = "Porządek wyników"

# --- komunikaty ogolne -------------------------------------------------------

#: Pasek stanu okna glownego.
STATUS_SEPARATOR = "   |   "
STATUS_INDEX_UNAVAILABLE = "Indeks niedostępny"
STATUS_SEMANTIC_ACTIVE = "Semantyka: aktywna"
STATUS_SEMANTIC_DISABLED = "Tryb semantyczny wyłączony"
STATUS_SEMANTIC_UNAVAILABLE = "Tryb semantyczny niedostępny"

BUTTON_OK = "OK"
BUTTON_CANCEL = "Anuluj"
BUTTON_CLOSE = "Zamknij"
BUTTON_SAVE = "Zapisz"
BUTTON_APPLY = "Zastosuj"
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
