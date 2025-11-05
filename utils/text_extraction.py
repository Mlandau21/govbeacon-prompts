"""Utilities for extracting and chunking text from SAM.gov attachments."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

import docx2txt
from pypdf import PdfReader


LOGGER = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}


class UnsupportedFileTypeError(Exception):
    """Raised when a requested file type is not supported."""


@dataclass
class ExtractedDocument:
    path: Path
    text: str
    extension: str


def extract_text(path: Path) -> ExtractedDocument:
    extension = path.suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileTypeError(f"Unsupported file extension: {extension}")

    if extension == ".pdf":
        text = _extract_pdf(path)
    elif extension == ".docx":
        text = _extract_docx(path)
    else:
        text = _extract_txt(path)

    normalized = _normalize_whitespace(text)
    return ExtractedDocument(path=path, text=normalized, extension=extension)


def chunk_text(text: str, *, chunk_size: int = 2000, overlap: int = 200) -> List[str]:
    if not text:
        return []

    words = text.split()
    if len(words) <= chunk_size:
        return [text]

    chunks: List[str] = []
    start = 0
    while start < len(words):
        end = min(len(words), start + chunk_size)
        chunk_words = words[start:end]
        chunks.append(" ".join(chunk_words))

        if end == len(words):
            break
        start = max(0, end - overlap)

    return chunks


def _extract_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = []
    for index, page in enumerate(reader.pages):
        try:
            pages.append(page.extract_text() or "")
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("Failed to extract text from %s page %s: %s", path, index, exc)
    return "\n".join(pages)


def _extract_docx(path: Path) -> str:
    try:
        return docx2txt.process(str(path))
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("Failed to extract text from %s: %s", path, exc)
        return ""


def _extract_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _normalize_whitespace(text: str) -> str:
    collapsed = re.sub(r"[\t\r]+", " ", text)
    collapsed = re.sub(r"\n{2,}", "\n\n", collapsed)
    return collapsed.strip()

