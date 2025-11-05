"""Generate attachment-level summaries using Gemini."""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import mimetypes
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from utils.gemini import GeminiClient, GeminiSettings
from utils.text_extraction import (
    SUPPORTED_EXTENSIONS,
    ExtractedDocument,
    UnsupportedFileTypeError,
    chunk_text,
    extract_text,
)
from google.genai import types


LOGGER = logging.getLogger(__name__)

DOC_PROMPT_PATH = Path(__file__).resolve().parent / "SAMgov_Document_Summarization_Prompt.md"
DOC_SUMMARIES_DIR_NAME = "doc_summaries"

MAX_DIRECT_WORDS = 4500
CHUNK_WORDS = 1800
CHUNK_OVERLAP = 200
CHUNK_SUMMARY_WORD_LIMIT = 180

CSV_HEADERS = [
    "sam-url",
    "opportunity_id",
    "filename",
    "filetype",
    "local_path",
    "detected_doc_type",
    "summary",
    "model",
    "run_id",
]


@dataclass
class AttachmentTask:
    opportunity_id: str
    sam_url: str
    path: Path
    relative_path: Path


@dataclass
class DocumentSummary:
    sam_url: str
    opportunity_id: str
    filename: str
    filetype: str
    local_path: str
    detected_doc_type: str
    summary: str
    model: str
    run_id: str
    error: Optional[str] = None

    def to_csv_row(self) -> Dict[str, str]:
        return {
            "sam-url": self.sam_url,
            "opportunity_id": self.opportunity_id,
            "filename": self.filename,
            "filetype": self.filetype,
            "local_path": self.local_path,
            "detected_doc_type": self.detected_doc_type,
            "summary": self.summary,
            "model": self.model,
            "run_id": self.run_id,
        }


def summarize_documents(
    *,
    attachments_dir: Path,
    output_dir: Path,
    metadata_csv: Optional[Path],
    model: str,
    run_id: Optional[str],
    max_workers: int,
    skip_existing: bool,
) -> None:
    attachments_dir = attachments_dir.resolve()
    output_dir = output_dir.resolve()
    summaries_dir = output_dir / DOC_SUMMARIES_DIR_NAME
    summaries_dir.mkdir(parents=True, exist_ok=True)

    if metadata_csv is None:
        raise ValueError("metadata_csv is required to map opportunity IDs to sam-url")

    metadata_map = _load_metadata_map(metadata_csv)
    if not metadata_map:
        LOGGER.warning("Metadata map is empty; no summaries will be generated")
        return

    tasks = _discover_attachment_tasks(attachments_dir, metadata_map)
    LOGGER.info("Discovered %s attachment(s)", len(tasks))

    if skip_existing:
        existing = _load_existing_summary_keys(summaries_dir)
        tasks = [
            task
            for task in tasks
            if (task.opportunity_id, task.path.name) not in existing
        ]
        LOGGER.info("Skipping %s already summarized attachment(s)", len(existing))
        LOGGER.info("%s attachment(s) remain after filtering", len(tasks))

    if not tasks:
        LOGGER.info("No attachments to summarize")
        return

    prompt_text = DOC_PROMPT_PATH.read_text(encoding="utf-8")
    run_identifier = run_id or datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    settings = GeminiSettings(model=model)

    results: List[DocumentSummary] = []

    LOGGER.info(
        "Starting document summarization for %s attachment(s) with model %s",
        len(tasks),
        model,
    )

    worker_count = max(1, max_workers)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(
                _summarize_single_attachment,
                task,
                settings,
                prompt_text,
                run_identifier,
            ): task
            for task in tasks
        }

        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:  # pylint: disable=broad-except
                LOGGER.exception(
                    "Failed to summarize %s (%s): %s",
                    task.path,
                    task.opportunity_id,
                    exc,
                )
                results.append(
                    DocumentSummary(
                        sam_url=task.sam_url,
                        opportunity_id=task.opportunity_id,
                        filename=task.path.name,
                        filetype=task.path.suffix.lower().lstrip("."),
                        local_path=str(task.relative_path),
                        detected_doc_type="",
                        summary="",
                        model=model,
                        run_id=run_identifier,
                        error=str(exc),
                    )
                )

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    sanitized_model = re.sub(r"[^A-Za-z0-9_-]+", "-", model)
    output_csv = summaries_dir / f"doc-summaries-{sanitized_model}-{timestamp}.csv"

    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for result in results:
            writer.writerow(result.to_csv_row())

    success_count = sum(1 for result in results if not result.error)
    error_count = len(results) - success_count

    LOGGER.info(
        "Wrote document summaries to %s (%s success, %s errors)",
        output_csv,
        success_count,
        error_count,
    )


def _summarize_single_attachment(
    task: AttachmentTask,
    settings: GeminiSettings,
    prompt_text: str,
    run_id: str,
) -> DocumentSummary:
    client = GeminiClient(settings)
    filetype = task.path.suffix.lower().lstrip(".")

    try:
        extracted = extract_text(task.path)
    except UnsupportedFileTypeError as exc:
        LOGGER.info(
            "Falling back to Gemini file upload for unsupported file %s: %s",
            task.path,
            exc,
        )
        return _summarize_with_file_upload(
            task=task,
            settings=settings,
            prompt_text=prompt_text,
            run_id=run_id,
        )
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Failed to extract text from %s", task.path)
        return _summarize_with_file_upload(
            task=task,
            settings=settings,
            prompt_text=prompt_text,
            run_id=run_id,
            fallback_error=f"extraction_error: {exc}",
        )

    if not extracted.text:
        LOGGER.warning("No text extracted from %s", task.path)
        return _summarize_with_file_upload(
            task=task,
            settings=settings,
            prompt_text=prompt_text,
            run_id=run_id,
            fallback_error="empty_document",
        )

    content_source, used_chunking = _prepare_document_content(extracted, client)

    user_text = _build_final_prompt(
        task=task,
        content=content_source,
        used_chunking=used_chunking,
    )

    try:
        summary_text = client.generate_text(
            user_text=user_text,
            system_instruction=prompt_text,
        )
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Gemini summarization failed for %s", task.path)
        return DocumentSummary(
            sam_url=task.sam_url,
            opportunity_id=task.opportunity_id,
            filename=task.path.name,
            filetype=filetype,
            detected_doc_type="",
            summary="",
            model=settings.model,
            run_id=run_id,
            error=f"gemini_error: {exc}",
        )

    summary_markdown, detected_type = _parse_summary_response(summary_text)
    return DocumentSummary(
        sam_url=task.sam_url,
        opportunity_id=task.opportunity_id,
        filename=task.path.name,
        filetype=filetype,
        local_path=str(task.relative_path),
        detected_doc_type=detected_type,
        summary=summary_markdown,
        model=settings.model,
        run_id=run_id,
    )


def _prepare_document_content(
    extracted: ExtractedDocument, client: GeminiClient
) -> tuple[str, bool]:
    words = extracted.text.split()
    if len(words) <= MAX_DIRECT_WORDS:
        return extracted.text, False

    chunks = chunk_text(
        extracted.text,
        chunk_size=CHUNK_WORDS,
        overlap=CHUNK_OVERLAP,
    )
    summaries: List[str] = []

    chunk_prompt_template = (
        "You are preparing notes for a later summarization step. "
        "Provide up to {limit} words of bullet points capturing the essential facts, requirements, "
        "dates, contract details, and notable instructions from the following document chunk ({index}/{total})."
        "\n\nChunk Content:\n{chunk}"
    )

    total = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        prompt = chunk_prompt_template.format(
            limit=CHUNK_SUMMARY_WORD_LIMIT,
            index=index,
            total=total,
            chunk=chunk,
        )
        try:
            summary = client.generate_text(user_text=prompt)
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("Chunk summarization failed (%s/%s): %s", index, total, exc)
            continue
        summaries.append(summary)

    if not summaries:
        LOGGER.warning("Chunk summarization produced no output; falling back to truncated text")
        truncated_words = words[:MAX_DIRECT_WORDS]
        return " ".join(truncated_words), True

    combined = "\n\n".join(summaries)
    return combined, True


def _build_final_prompt(*, task: AttachmentTask, content: str, used_chunking: bool) -> str:
    header = (
        "The following consolidated notes come from chunk-level summaries of the document. "
        "Integrate them into a complete summary."
    ) if used_chunking else "Document Content"

    return (
        f"Filename: {task.path.name}\n"
        f"Opportunity ID: {task.opportunity_id}\n"
        f"SAM URL: {task.sam_url}\n\n"
        f"{header}:\n```text\n{content}\n```"
    )


def _parse_summary_response(response: str) -> tuple[str, str]:
    """Parse summary response and extract markdown content and document type.
    
    Supports two formats:
    1. JSON format: {"document_summary": "..."} (may be wrapped in ```json code blocks)
    2. Legacy plain text format: "Detected Document Type: ..."
    
    Returns:
        tuple: (summary_markdown, detected_doc_type)
    """
    response = response.strip()
    
    # Try JSON format first
    try:
        # Strip markdown code block markers if present
        cleaned = response
        if cleaned.startswith('```json'):
            cleaned = cleaned[7:]  # Remove ```json
        elif cleaned.startswith('```'):
            cleaned = cleaned[3:]  # Remove ```
        if cleaned.endswith('```'):
            cleaned = cleaned[:-3]  # Remove closing ```
        cleaned = cleaned.strip()
        
        # Find the start of JSON object
        start_idx = cleaned.find('{')
        if start_idx != -1:
            # Find matching closing brace
            depth = 0
            end_idx = start_idx
            for i in range(start_idx, len(cleaned)):
                if cleaned[i] == '{':
                    depth += 1
                elif cleaned[i] == '}':
                    depth -= 1
                    if depth == 0:
                        end_idx = i + 1
                        break
            
            json_str = cleaned[start_idx:end_idx]
            data = json.loads(json_str)
            
            if "document_summary" in data:
                summary_markdown = data["document_summary"].strip()
                # Extract document type from markdown (look for "### Document Type" header)
                doc_type = _extract_doc_type_from_markdown(summary_markdown)
                return summary_markdown, doc_type
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        LOGGER.debug("JSON parsing failed, falling back to legacy format: %s", e)
        pass
    
    # Fall back to legacy plain text format
    detected_type = _parse_detected_doc_type_legacy(response)
    return response, detected_type


def _extract_doc_type_from_markdown(markdown: str) -> str:
    """Extract document type from markdown content.
    
    Looks for "### Document Type" header followed by the type on the next line.
    """
    # Pattern to match "### Document Type" followed by the type on same or next line
    pattern = re.compile(r"###\s*Document Type\s*\n\s*(.+?)(?:\n|$)", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(markdown)
    if match:
        doc_type = match.group(1).strip()
        # Clean up markdown formatting
        doc_type = re.sub(r"\*+", "", doc_type)
        doc_type = re.sub(r"^#+\s*", "", doc_type)
        return doc_type
    
    # Fallback: look for just "Document Type:" pattern
    pattern2 = re.compile(r"Document Type[:\s]+\s*(.+?)(?:\n|$)", re.IGNORECASE | re.MULTILINE)
    match2 = pattern2.search(markdown)
    if match2:
        doc_type = match2.group(1).strip()
        doc_type = re.sub(r"\*+", "", doc_type)
        return doc_type
    
    return ""


def _parse_detected_doc_type_legacy(summary: str) -> str:
    """Parse document type from legacy format: "Detected Document Type: ..." """
    pattern = re.compile(r"Detected Document Type:\s*(.+)")
    match = pattern.search(summary)
    if not match:
        return ""
    doc_type = match.group(1).strip()
    doc_type = re.sub(r"\*+", "", doc_type)
    return doc_type


def _summarize_with_file_upload(
    *,
    task: AttachmentTask,
    settings: GeminiSettings,
    prompt_text: str,
    run_id: str,
    fallback_error: Optional[str] = None,
) -> DocumentSummary:
    client = GeminiClient(settings)
    filetype = task.path.suffix.lower().lstrip(".")

    try:
        file_bytes = task.path.read_bytes()
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Failed to read file bytes for %s", task.path)
        return DocumentSummary(
            sam_url=task.sam_url,
            opportunity_id=task.opportunity_id,
            filename=task.path.name,
            filetype=filetype,
            local_path=str(task.relative_path),
            detected_doc_type="",
            summary="",
            model=settings.model,
            run_id=run_id,
            error=f"read_error: {exc}",
        )

    mime_type = _detect_mime_type(task.path, file_bytes=file_bytes)

    parts = [
        types.Part.from_text(text=_build_file_prompt(task)),
        types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
    ]

    try:
        summary_text = client.generate_from_parts(
            parts=parts,
            system_instruction=prompt_text,
        )
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Gemini file upload summarization failed for %s", task.path)
        error_msg = fallback_error or ""
        error_suffix = f"file_upload_error: {exc}"
        error_msg = f"{error_msg}; {error_suffix}" if error_msg else error_suffix
        return DocumentSummary(
            sam_url=task.sam_url,
            opportunity_id=task.opportunity_id,
            filename=task.path.name,
            filetype=filetype,
            local_path=str(task.relative_path),
            detected_doc_type="",
            summary="",
            model=settings.model,
            run_id=run_id,
            error=error_msg,
        )

    summary_markdown, detected_type = _parse_summary_response(summary_text)
    return DocumentSummary(
        sam_url=task.sam_url,
        opportunity_id=task.opportunity_id,
        filename=task.path.name,
        filetype=filetype,
        local_path=str(task.relative_path),
        detected_doc_type=detected_type,
        summary=summary_markdown,
        model=settings.model,
        run_id=run_id,
    )


def _build_file_prompt(task: AttachmentTask) -> str:
    return (
        f"Filename: {task.path.name}\n"
        f"Opportunity ID: {task.opportunity_id}\n"
        f"SAM URL: {task.sam_url}\n\n"
        "The source document is attached. Summarize it according to the instructions."
    )


def _detect_mime_type(path: Path, *, file_bytes: Optional[bytes] = None) -> str:
    suffix = path.suffix.lower()
    if suffix == ".doc":
        return "application/msword"
    if suffix == ".xls":
        return "application/vnd.ms-excel"
    if suffix == ".ppt":
        return "application/vnd.ms-powerpoint"

    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                if any(name.startswith("word/") for name in names):
                    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                if any(name.startswith("xl/") for name in names):
                    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                if any(name.startswith("ppt/") for name in names):
                    return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        except Exception:  # pylint: disable=broad-except
            LOGGER.debug("Unable to inspect zip archive for %s", path)
        if suffix == ".docx":
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if suffix == ".xlsx":
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if suffix == ".pptx":
            return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        return "application/zip"

    header = None
    if file_bytes is not None:
        header = file_bytes[:8]
    else:
        try:
            with path.open("rb") as handle:
                header = handle.read(8)
        except Exception:  # pylint: disable=broad-except
            header = None

    if header and header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        if suffix in {".doc", ".docx"}:
            return "application/msword"
        if suffix in {".xls", ".xlsx"}:
            return "application/vnd.ms-excel"
        if suffix in {".ppt", ".pptx"}:
            return "application/vnd.ms-powerpoint"

    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _load_metadata_map(metadata_csv: Path) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    with metadata_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if "opportunity_id" not in reader.fieldnames or "sam-url" not in reader.fieldnames:
            raise ValueError("metadata CSV must include 'opportunity_id' and 'sam-url' columns")
        for row in reader:
            opportunity_id = row.get("opportunity_id")
            sam_url = row.get("sam-url")
            if not opportunity_id or not sam_url:
                continue
            mapping[opportunity_id] = sam_url
    return mapping


def _discover_attachment_tasks(
    attachments_dir: Path, metadata_map: Dict[str, str]
) -> List[AttachmentTask]:
    tasks: List[AttachmentTask] = []
    for opportunity_dir in attachments_dir.iterdir():
        if not opportunity_dir.is_dir():
            continue
        opportunity_id = opportunity_dir.name
        sam_url = metadata_map.get(opportunity_id)
        if not sam_url:
            LOGGER.warning("No sam-url mapping found for %s; skipping", opportunity_id)
            continue

        for file_path in opportunity_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            relative_path = file_path.relative_to(attachments_dir)
            tasks.append(
                AttachmentTask(
                    opportunity_id=opportunity_id,
                    sam_url=sam_url,
                    path=file_path,
                    relative_path=relative_path,
                )
            )

    return tasks


def _load_existing_summary_keys(directory: Path) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    if not directory.exists():
        return keys

    for csv_path in directory.glob("doc-summaries-*.csv"):
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                keys.add((row.get("opportunity_id", ""), row.get("filename", "")))
    return keys

