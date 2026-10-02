"""Per-page OCR results on disk.

OCR'ing a 500-page book takes tens of minutes. Without this, a deploy, a crash
or a retry in the middle would start it over: `recovery` re-queues the
material, and the run picks up from the pages already stored here.

Keyed by the raw file's SHA-256, so the cache follows the content, not the
material row.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict
from pathlib import Path

import regex

from apps.pipeline.ocr.base import PageResult

logger = logging.getLogger(__name__)

_SHA256 = regex.compile(r"^[0-9a-f]{64}$")


class OcrCache:
    def __init__(self, root: Path, file_hash: str, dpi: int):
        # The hash becomes a directory name: never let anything else in.
        if not _SHA256.match(file_hash or ""):
            raise ValueError(f"Noto'g'ri fayl xeshi: {file_hash!r}")
        self.directory = root / file_hash
        self.dpi = dpi

    def get(self, page: int) -> PageResult | None:
        path = self._path(page)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            logger.warning("OCR kesh fayli buzilgan (%s): %s", path, exc)
            return None
        # A different resolution reads differently; failed pages get retried.
        if payload.pop("dpi", None) != self.dpi or payload.get("error"):
            return None
        try:
            return PageResult(**payload)
        except TypeError:
            return None

    def put(self, result: PageResult) -> None:
        if result.error:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(result.page)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({**asdict(result), "dpi": self.dpi}, ensure_ascii=False),
            encoding="utf-8",
        )
        # Atomic: a crash mid-write never leaves a half page behind.
        os.replace(temporary, path)

    def clear(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)

    def _path(self, page: int) -> Path:
        return self.directory / f"page-{page:05d}.json"


def remove_cache(root: Path, file_hash: str | None) -> None:
    if not file_hash or not _SHA256.match(file_hash):
        return
    shutil.rmtree(root / file_hash, ignore_errors=True)
