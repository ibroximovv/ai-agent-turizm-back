"""Thin wrapper around the `tesseract` command-line program.

The binary is called directly rather than through pytesseract: it is the same
subprocess call, and owning it keeps the error messages in Uzbek and the TSV
parsing (which gives us per-word confidence) in one place.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from apps.pipeline.ocr.base import OcrError, OcrUnavailableError

#: Neural (LSTM) engine only — the legacy engine is slower and less accurate.
ENGINE_MODE = "1"
#: Fully automatic page segmentation: the right default for book pages.
PAGE_SEGMENTATION_MODE = "3"


class PageTimeoutError(OcrError):
    """One page took longer than the configured limit."""


@dataclass(frozen=True)
class TesseractResult:
    text: str
    confidence: float


def recognize(
    image: bytes,
    languages: str,
    *,
    dpi: int,
    timeout: float,
    cmd: str = "tesseract",
    tessdata_dir: str = "",
) -> TesseractResult:
    """OCR one encoded page image (PNG / PNM) fed through stdin."""
    args = [
        cmd,
        "stdin",
        "stdout",
        "-l",
        languages,
        "--oem",
        ENGINE_MODE,
        "--psm",
        PAGE_SEGMENTATION_MODE,
        "--dpi",
        str(dpi),
    ]
    if tessdata_dir:
        args += ["--tessdata-dir", tessdata_dir]
    args.append("tsv")

    try:
        completed = subprocess.run(
            args,
            input=image,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=_environment(),
        )
    except FileNotFoundError as exc:
        raise OcrUnavailableError(
            f"Tesseract o'rnatilmagan ({cmd} topilmadi). Serverga o'rnating: "
            "apt install tesseract-ocr tesseract-ocr-uzb tesseract-ocr-uzb-cyrl "
            "tesseract-ocr-rus"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise PageTimeoutError(f"sahifa {timeout:.0f} s ichida o'qilmadi") from exc

    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        if "Failed loading language" in stderr or "Error opening data file" in stderr:
            raise OcrUnavailableError(
                f"Tesseract til paketi topilmadi ({languages}): {_last_line(stderr)}"
            )
        raise OcrError(f"Tesseract xatosi: {_last_line(stderr) or completed.returncode}")

    return parse_tsv(completed.stdout.decode("utf-8", errors="replace"))


def list_languages(cmd: str = "tesseract", tessdata_dir: str = "") -> list[str]:
    """Installed language packs. Raises `OcrUnavailableError` without a binary."""
    args = [cmd, "--list-langs"]
    if tessdata_dir:
        args += ["--tessdata-dir", tessdata_dir]
    try:
        completed = subprocess.run(
            args, capture_output=True, timeout=30, check=False, env=_environment()
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise OcrUnavailableError(f"Tesseract ishga tushmadi ({cmd}): {exc}") from exc

    # The first line is a header ("List of available languages in ...").
    output = completed.stdout.decode("utf-8", errors="replace").splitlines()
    return [line.strip() for line in output[1:] if line.strip()]


def parse_tsv(tsv: str) -> TesseractResult:
    """Rebuild the page text from Tesseract's TSV output.

    Words on one line are joined by spaces, lines by a newline and paragraphs
    by a blank line — the shape `clean_text` expects (it unwraps single
    newlines and keeps blank lines as paragraph breaks).
    """
    paragraphs: list[list[list[str]]] = []
    current_key: tuple[str, str] | None = None
    current_line: tuple[str, str, str] | None = None
    confidences: list[float] = []

    for row in tsv.splitlines()[1:]:
        cells = row.split("\t")
        # level page block par line word left top width height conf text
        if len(cells) < 12 or cells[0] != "5":
            continue
        word = cells[11].strip()
        if not word:
            continue
        try:
            conf = float(cells[10])
        except ValueError:
            conf = -1.0
        if conf >= 0:
            confidences.append(conf)

        block, par, line = cells[2], cells[3], cells[4]
        if (block, par) != current_key:
            paragraphs.append([])
            current_key = (block, par)
            current_line = None
        if (block, par, line) != current_line:
            paragraphs[-1].append([])
            current_line = (block, par, line)
        paragraphs[-1][-1].append(word)

    text = "\n\n".join("\n".join(" ".join(words) for words in lines) for lines in paragraphs)
    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return TesseractResult(text=text, confidence=round(confidence, 1))


def _environment() -> dict[str, str]:
    # Tesseract parallelises one page over OpenMP threads by default. We run
    # several pages side by side instead, so the inner threads would only
    # oversubscribe the CPU.
    return {**os.environ, "OMP_THREAD_LIMIT": "1"}


def _last_line(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""
