"""FindDocs: lokalna wyszukiwarka dokumentow korporacyjnych.

Pakiet dzieli sie na warstwy o jednokierunkowych zaleznosciach:

``connectors`` -> ``extractors``/``ocr`` -> ``normalization``/``chunking``
-> ``indexing`` -> ``search`` -> ``jobs`` -> ``gui``.
"""

from __future__ import annotations

from finddocs.version import APP_NAME, APP_VERSION, SCHEMA_VERSION

__all__ = ["APP_NAME", "APP_VERSION", "SCHEMA_VERSION", "__version__"]

__version__ = APP_VERSION
