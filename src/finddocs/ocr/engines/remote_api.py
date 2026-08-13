"""Adapter zdalnego serwera OCR liczacego na GPU.

Silniki lokalne (Tesseract, RapidOCR, EasyOCR) pracuja na procesorze i sa
najwolniejszym etapem indeksowania. Ten adapter pozwala oddac rozpoznawanie
serwerowi organizacji z karta graficzna, na przyklad kontenerowi z modelem
PP-OCRv6_medium (katalog ``deploy/ppocr`` w repozytorium).

Silnik jest domyslnie nieaktywny. Uruchomienie wymaga swiadomej decyzji:

1. ustawienia ``ocr.remote_api_enabled`` na true;
2. podania adresu ``ocr.remote_api_url``;
3. wlaczenia kategorii ruchu ``ocr_api`` w polityce sieciowej (aplikacja robi
   to na podstawie punktu 1 i dopuszcza wylacznie host z podanego adresu);
4. wybrania silnika: ``ocr.engine = "remote_api"``.

Bez tego kompletu ``is_available`` zwraca falsz, a aplikacja pracuje lokalnie.
Chodzi o to, zeby obraz strony dokumentu nie opuscil komputera przez
przypadkowa konfiguracje.

Kontrakt HTTP to standard serwowania PaddleX (``POST {base_url}/ocr``), ten sam
dla PP-OCRv5 i PP-OCRv6. Cialo zadania niesie obraz strony zakodowany base64,
odpowiedz ma postac::

    {"errorCode": 0, "result": {"ocrResults": [{"prunedResult": {
        "rec_texts": [...], "rec_scores": [...], "dt_polys": [...]}}]}}

Strony ida pojedynczo, tak samo jak w silnikach lokalnych: zuzycie pamieci nie
zalezy od liczby stron, a anulowanie dziala miedzy stronami.

Klucz API nigdy nie trafia do logow ani do pliku konfiguracyjnego. Adapter
dostaje funkcje zwracajaca klucz i odczytuje go dopiero przy wysylce.
"""

from __future__ import annotations

import base64
import io
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from finddocs.errors import NetworkPolicyError, OcrRemoteError
from finddocs.logging_setup import get_logger
from finddocs.ocr.base import OcrEngine, OcrLine, OcrPageResult
from finddocs.security.network import EgressCategory, NetworkPolicy, get_policy
from finddocs.security.redaction import safe_url
from finddocs.types import CancellationToken

if TYPE_CHECKING:  # pragma: no cover - tylko dla kontroli typow
    from PIL.Image import Image

log = get_logger(__name__)

ENGINE_NAME = "remote_api"

#: Domyslny limit czasu jednego zadania. Strona A4 na GPU idzie w ulamku
#: sekundy, ale kolejka na obcialonym serwerze potrafi wydluzyc odpowiedz.
DEFAULT_TIMEOUT_SECONDS = 120.0

#: Limit czasu sprawdzenia, czy serwer w ogole odpowiada.
PROBE_TIMEOUT_SECONDS = 5.0

#: Kody HTTP traktowane jako przejsciowe: warto ponowic probe.
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})

#: Podstawa i gorna granica odczekania miedzy probami (sekundy).
RETRY_BACKOFF_BASE_SECONDS = 0.5
RETRY_BACKOFF_MAX_SECONDS = 8.0

#: Jezyki obslugiwane przez modele PP-OCR, do ktorych adresowany jest adapter.
#: Rozpoznawanie polskich znakow diakrytycznych zweryfikowano na kontenerze
#: z PP-OCRv6_medium (opis w docs/ocr-gpu-api.md).
REMOTE_LANGUAGES: tuple[str, ...] = ("pol", "eng")


def _sleep_with_cancel(seconds: float, cancel: CancellationToken | None) -> None:
    """Odczekuje miedzy probami, przerywajac natychmiast po anulowaniu."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if cancel is not None:
            cancel.raise_if_cancelled()
        time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
    if cancel is not None:
        cancel.raise_if_cancelled()


def _encode_png(image: Image) -> str:
    """Koduje strone do PNG w base64. Bezstratnie, bo artefakty psuja OCR."""
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=False)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _rect_from_polygon(polygon: Any) -> tuple[int, int, int, int] | None:
    """Zamienia wielokat detekcji na prostokat (x, y, szerokosc, wysokosc)."""
    try:
        points = [(int(point[0]), int(point[1])) for point in polygon]
    except (IndexError, TypeError, ValueError):
        return None
    if not points:
        return None
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


class RemoteOcrEngine(OcrEngine):
    """OCR na zdalnym serwerze PaddleX (PP-OCRv6 i pokrewne)."""

    name = ENGINE_NAME
    #: Wyzszy niz silniki lokalne: gdy administrator swiadomie skonfigurowal
    #: serwer, to on ma byc pierwszym wyborem.
    priority = 90
    supports_rotation = True
    provides_confidence = True

    def __init__(
        self,
        base_url: str,
        *,
        enabled: bool,
        model: str = "",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = 3,
        api_key_provider: Callable[[], str | None] | None = None,
        api_key_header: str = "",
        auto_rotate: bool = True,
        policy: NetworkPolicy | None = None,
        transport: Any | None = None,
    ) -> None:
        """``transport`` to hak testowy: pozwala podstawic httpx.MockTransport."""
        self._enabled = enabled
        self._base_url = (base_url or "").strip().rstrip("/")
        self._model = (model or "").strip()
        self._timeout = max(1.0, timeout)
        self._max_retries = max(1, max_retries)
        self._api_key_provider = api_key_provider
        self._api_key_header = api_key_header.strip()
        self._auto_rotate = auto_rotate
        self._policy = policy or get_policy()
        self._transport = transport
        self._client: Any | None = None
        self._available: bool | None = None
        self._reason = ""

    # --- dostepnosc -------------------------------------------------------

    @property
    def endpoint(self) -> str:
        return f"{self._base_url}/ocr"

    def is_available(self) -> bool:
        """Sprawdza zgode, adres, polityke sieciowa i odpowiedz serwera.

        Wynik jest zapamietywany, wiec proba polaczenia idzie raz na cykl zycia
        silnika. Niedostepny serwer nie blokuje indeksowania: usluga OCR
        przechodzi wtedy na silnik lokalny i zapisuje to w dzienniku.
        """
        if self._available is not None:
            return self._available
        self._available = False
        if not self._enabled:
            self._reason = (
                "Zdalny serwer OCR jest wyłączony. Włącz go świadomie w ustawieniach, "
                "jeśli organizacja go udostępniła."
            )
            return False
        if not self._base_url:
            self._reason = "Nie podano adresu zdalnego serwera OCR."
            return False
        try:
            self._policy.check(self.endpoint, EgressCategory.OCR_API)
        except NetworkPolicyError as exc:
            self._reason = exc.user_message
            return False
        reachable, detail = self._probe()
        if not reachable:
            self._reason = (
                f"Zdalny serwer OCR pod adresem {safe_url(self._base_url)} "
                f"nie odpowiada ({detail})."
            )
            log.warning("ocr.remote_unreachable", url=safe_url(self._base_url), reason=detail)
            return False
        self._available = True
        return True

    def _probe(self) -> tuple[bool, str]:
        """Pyta serwer o stan. Kazda odpowiedz HTTP oznacza, ze serwer zyje.

        Kod odpowiedzi celowo nie jest sprawdzany: nie kazde wdrozenie wystawia
        ``/health``, a odpowiedz 404 rowniez dowodzi, ze usluga dziala.
        """
        import httpx

        try:
            client = self._http_client()
            client.get(f"{self._base_url}/health", timeout=PROBE_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            return False, type(exc).__name__
        return True, "ok"

    def unavailable_reason(self) -> str:
        self.is_available()
        return self._reason

    def version(self) -> str:
        """Nazwa modelu po stronie serwera.

        Wchodzi do klucza pamieci podrecznej OCR, wiec zmiana modelu na serwerze
        powinna isc w parze ze zmiana tego ustawienia. Inaczej stare wyniki
        zostana odczytane jako wlasne.
        """
        return self._model or "zdalny"

    def supported_languages(self) -> list[str]:
        return list(REMOTE_LANGUAGES)

    def has_polish(self) -> bool:
        return "pol" in REMOTE_LANGUAGES

    # --- polaczenie -------------------------------------------------------

    def _http_client(self) -> Any:
        if self._client is None:
            import httpx

            kwargs: dict[str, Any] = {"timeout": self._timeout}
            if self._transport is not None:
                kwargs["transport"] = self._transport
            self._client = httpx.Client(**kwargs)
        return self._client

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        key = self._api_key_provider() if self._api_key_provider is not None else None
        if key:
            if self._api_key_header:
                headers[self._api_key_header] = key
            else:
                headers["authorization"] = f"Bearer {key}"
        return headers

    def _request_body(self, encoded: str) -> dict[str, Any]:
        return {
            "file": encoded,
            "fileType": 1,
            # Obraz jest juz wyprostowany i przyciety przez warstwe renderowania,
            # wiec dwa pierwsze etapy potoku tylko kosztowalyby czas.
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useTextlineOrientation": self._auto_rotate,
            # Bez tego serwer dokleja do odpowiedzi podglad strony w base64.
            "visualize": False,
        }

    def _post_once(self, body: dict[str, Any]) -> Any:
        import httpx

        client = self._http_client()
        try:
            response = client.post(self.endpoint, json=body, headers=self._headers())
        except httpx.HTTPError as exc:
            raise _TransientRemoteError(type(exc).__name__) from exc
        if response.status_code in RETRYABLE_STATUS_CODES:
            raise _TransientRemoteError(f"HTTP {response.status_code}")
        if response.status_code in (401, 403):
            raise OcrRemoteError(
                "Zdalny serwer OCR odrzucił uwierzytelnienie. Sprawdź klucz API w ustawieniach OCR."
            )
        try:
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise OcrRemoteError(
                "Zdalny serwer OCR nie odpowiedział poprawnie.", cause=exc
            ) from exc

    def _post_page(self, encoded: str, page: int, cancel: CancellationToken | None) -> Any:
        self._policy.check(self.endpoint, EgressCategory.OCR_API)
        body = self._request_body(encoded)

        last_reason = ""
        for attempt in range(1, self._max_retries + 1):
            if cancel is not None:
                cancel.raise_if_cancelled()
            try:
                return self._post_once(body)
            except _TransientRemoteError as exc:
                last_reason = exc.reason
                log.warning(
                    "ocr.remote_retry",
                    attempt=attempt,
                    max_attempts=self._max_retries,
                    page=page,
                    reason=exc.reason,
                )
                if attempt < self._max_retries:
                    delay = min(
                        RETRY_BACKOFF_MAX_SECONDS,
                        RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
                    )
                    _sleep_with_cancel(delay, cancel)
        raise OcrRemoteError(
            f"Zdalny serwer OCR nie odpowiedział mimo {self._max_retries} prób. "
            f"Ostatni powód: {last_reason}."
        )

    # --- odpowiedz --------------------------------------------------------

    def _parse_payload(self, payload: Any) -> list[OcrLine]:
        """Wyciaga linie tekstu z odpowiedzi serwera PaddleX."""
        if not isinstance(payload, dict):
            raise OcrRemoteError("Zdalny serwer OCR zwrócił odpowiedź w nieznanym formacie.")
        error_code = payload.get("errorCode")
        if error_code not in (None, 0):
            message = str(payload.get("errorMsg") or "brak opisu")
            raise OcrRemoteError(f"Zdalny serwer OCR zgłosił błąd {error_code}: {message}.")

        result = payload.get("result")
        entries = result.get("ocrResults") if isinstance(result, dict) else None
        if not isinstance(entries, list):
            raise OcrRemoteError("Zdalny serwer OCR nie zwrócił wyników rozpoznawania.")
        if not entries:
            return []

        pruned = entries[0].get("prunedResult") if isinstance(entries[0], dict) else None
        if not isinstance(pruned, dict):
            raise OcrRemoteError("Zdalny serwer OCR zwrócił wynik bez rozpoznanego tekstu.")

        texts = pruned.get("rec_texts") or []
        scores = pruned.get("rec_scores") or []
        polygons = pruned.get("dt_polys") or []
        if not isinstance(texts, list):
            raise OcrRemoteError("Zdalny serwer OCR zwrócił listę tekstów w złym formacie.")

        lines: list[OcrLine] = []
        for index, text in enumerate(texts):
            value = str(text)
            if not value.strip():
                continue
            score: float | None = None
            if index < len(scores):
                try:
                    score = float(scores[index])
                except (TypeError, ValueError):
                    score = None
            box = _rect_from_polygon(polygons[index]) if index < len(polygons) else None
            lines.append(OcrLine(text=value, confidence=score, box=box))
        return lines

    # --- rozpoznawanie ----------------------------------------------------

    def recognize(
        self,
        image: Image,
        *,
        languages: list[str],
        page: int = 1,
        cancel: CancellationToken | None = None,
    ) -> OcrPageResult:
        del languages  # model jest wybierany po stronie serwera, nie per strona
        if cancel is not None:
            cancel.raise_if_cancelled()
        if not self.is_available():
            raise OcrRemoteError(self.unavailable_reason())

        started = time.monotonic()
        encoded = _encode_png(image)
        payload = self._post_page(encoded, page, cancel)
        lines = self._parse_payload(payload)

        # Serwer zwraca linie w kolejnosci detekcji. Porzadek czytania (od gory,
        # potem od lewej) jest stabilniejszy i zgodny z silnikami lokalnymi.
        lines.sort(
            key=lambda line: (line.box[1] if line.box else 0, line.box[0] if line.box else 0)
        )
        confidences = [line.confidence for line in lines if line.confidence is not None]
        average = sum(confidences) / len(confidences) if confidences else None
        return OcrPageResult(
            page=page,
            text="\n".join(line.text for line in lines),
            confidence=average,
            lines=lines,
            engine=self.name,
            duration_seconds=time.monotonic() - started,
        )

    def ping(self) -> dict[str, Any]:
        """Sprawdza polaczenie na potrzeby przycisku testu w interfejsie.

        Wysyla maly, sztuczny obraz przez ten sam kontrakt, ktorego uzywa
        indeksowanie. Dzieki temu test wykrywa nie tylko martwy serwer, ale tez
        odrzucony klucz API czy niezgodny kontrakt.
        """
        from PIL import Image as PilImage

        self._policy.check(self.endpoint, EgressCategory.OCR_API)
        probe = PilImage.new("RGB", (64, 32), color=(255, 255, 255))
        started = time.monotonic()
        try:
            payload = self._post_once(self._request_body(_encode_png(probe)))
        except _TransientRemoteError as exc:
            raise OcrRemoteError(f"Zdalny serwer OCR nie odpowiedział ({exc.reason}).") from exc
        finally:
            probe.close()
        self._parse_payload(payload)
        return {
            "adres": safe_url(self._base_url),
            "model": self.version(),
            "czas_odpowiedzi_s": round(time.monotonic() - started, 3),
        }

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None

    def describe(self) -> dict[str, Any]:
        data = super().describe()
        data["adres"] = safe_url(self._base_url) if self._base_url else ""
        data["klucz_api"] = "skonfigurowany" if self._api_key_provider is not None else "brak"
        return data


class _TransientRemoteError(Exception):
    """Wewnetrzny sygnal bledu przejsciowego, obslugiwany przez ponowienia."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "ENGINE_NAME",
    "PROBE_TIMEOUT_SECONDS",
    "REMOTE_LANGUAGES",
    "RETRYABLE_STATUS_CODES",
    "RemoteOcrEngine",
]
