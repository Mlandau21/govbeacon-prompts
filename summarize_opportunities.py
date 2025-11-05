"""Generate opportunity-level summaries combining metadata and document summaries."""

from __future__ import annotations

import csv
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from utils.gemini import GeminiClient, GeminiSettings


LOGGER = logging.getLogger(__name__)

OPP_PROMPT_PATH = Path(__file__).resolve().parent / "SAMgov_Opportunity_Summarization_Prompt.md"
OPP_SUMMARIES_DIR_NAME = "opportunity_summaries"

CSV_HEADERS = [
    "sam-url",
    "govbeacon-long-summary",
    "govbeacon-short-summary",
    "model",
    "run_id",
]


@dataclass
class OpportunityData:
    sam_url: str
    opportunity_id: str
    metadata: Dict[str, str]
    documents: List[Dict[str, str]]


@dataclass
class OpportunitySummary:
    sam_url: str
    long_summary: str
    short_summary: str
    model: str
    run_id: str
    error: Optional[str] = None

    def to_csv_row(self) -> Dict[str, str]:
        return {
            "sam-url": self.sam_url,
            "govbeacon-long-summary": self.long_summary,
            "govbeacon-short-summary": self.short_summary,
            "model": self.model,
            "run_id": self.run_id,
        }


def summarize_opportunities(
    *,
    metadata_csv: Path,
    doc_summaries_csv: Path,
    output_dir: Path,
    model: str,
    run_id: Optional[str],
    max_workers: int,
) -> None:
    output_dir = output_dir.resolve()
    summaries_dir = output_dir / OPP_SUMMARIES_DIR_NAME
    summaries_dir.mkdir(parents=True, exist_ok=True)

    prompt_text = OPP_PROMPT_PATH.read_text(encoding="utf-8")
    run_identifier = run_id or datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    settings = GeminiSettings(model=model)

    opportunities = _merge_metadata_with_documents(metadata_csv, doc_summaries_csv)
    if not opportunities:
        LOGGER.warning("No opportunities found to summarize")
        return

    LOGGER.info(
        "Generating opportunity summaries for %s item(s) using model %s",
        len(opportunities),
        model,
    )

    results: List[OpportunitySummary] = []
    worker_count = max(1, max_workers)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(
                _summarize_single_opportunity,
                opportunity,
                settings,
                prompt_text,
                run_identifier,
            ): opportunity
            for opportunity in opportunities
        }

        for future in as_completed(futures):
            opportunity = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # pylint: disable=broad-except
                LOGGER.exception(
                    "Failed to summarize opportunity %s", opportunity.sam_url
                )
                results.append(
                    OpportunitySummary(
                        sam_url=opportunity.sam_url,
                        long_summary="",
                        short_summary="",
                        model=model,
                        run_id=run_identifier,
                        error=str(exc),
                    )
                )

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    sanitized_model = re.sub(r"[^A-Za-z0-9_-]+", "-", model)
    output_csv = summaries_dir / f"sam-summary-{sanitized_model}-{timestamp}.csv"

    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for result in results:
            writer.writerow(result.to_csv_row())

    success_count = sum(1 for result in results if not result.error)
    error_count = len(results) - success_count

    LOGGER.info(
        "Wrote opportunity summaries to %s (%s success, %s errors)",
        output_csv,
        success_count,
        error_count,
    )


def _summarize_single_opportunity(
    opportunity: OpportunityData,
    settings: GeminiSettings,
    prompt_text: str,
    run_id: str,
) -> OpportunitySummary:
    client = GeminiClient(settings)
    user_text = _build_opportunity_prompt(opportunity)

    try:
        response = client.generate_text(
            user_text=user_text,
            system_instruction=prompt_text,
        )
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Gemini call failed for %s", opportunity.sam_url)
        return OpportunitySummary(
            sam_url=opportunity.sam_url,
            long_summary="",
            short_summary="",
            model=settings.model,
            run_id=run_id,
            error=f"gemini_error: {exc}",
        )

    long_summary, short_summary = _split_long_short(response)
    return OpportunitySummary(
        sam_url=opportunity.sam_url,
        long_summary=long_summary,
        short_summary=short_summary,
        model=settings.model,
        run_id=run_id,
    )


def _build_opportunity_prompt(opportunity: OpportunityData) -> str:
    lines: List[str] = []
    lines.append("Opportunity Metadata:")
    for key, value in opportunity.metadata.items():
        if not value:
            continue
        pretty_key = key.replace("_", " ").title()
        lines.append(f"- {pretty_key}: {value}")

    lines.append("\nDocument Summaries:")
    if opportunity.documents:
        for index, document in enumerate(opportunity.documents, start=1):
            title = document.get("filename", f"Document {index}")
            doc_type = document.get("detected_doc_type")
            summary = document.get("summary", "")
            lines.append(f"{index}. {title}")
            if doc_type:
                lines.append(f"   Type: {doc_type}")
            if summary:
                lines.append(f"   Summary: {summary}")
    else:
        lines.append("No document summaries available. Use metadata only.")

    return "\n".join(lines)


def _split_long_short(response: str) -> tuple[str, str]:
    # Match "Short Summary" with optional bold/formatting, followed by optional text on same line, then newlines
    # This captures headers like "### **Short Summary (≤130 words)**" or "**Short Summary:**"
    pattern = re.compile(r"#+\s*\*{0,2}Short Summary[^\n]*\*{0,2}\s*\n+", re.IGNORECASE)
    match = pattern.search(response)
    if not match:
        return response.strip(), ""

    long_summary = response[: match.start()].strip()
    short_summary = response[match.end() :].strip()
    return long_summary, short_summary


def _merge_metadata_with_documents(
    metadata_csv: Path, doc_summaries_csv: Path
) -> List[OpportunityData]:
    metadata_rows = _load_metadata_rows(metadata_csv)
    doc_rows = _load_document_rows(doc_summaries_csv)

    opportunities: List[OpportunityData] = []
    for opportunity_id, meta in metadata_rows.items():
        documents = doc_rows.get(opportunity_id, [])
        opportunities.append(
            OpportunityData(
                sam_url=meta["sam-url"],
                opportunity_id=opportunity_id,
                metadata=meta,
                documents=documents,
            )
        )

    return opportunities


def _load_metadata_rows(metadata_csv: Path) -> Dict[str, Dict[str, str]]:
    rows: Dict[str, Dict[str, str]] = {}
    with metadata_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"opportunity_id", "sam-url"}
        if not required.issubset(reader.fieldnames or {}):
            raise ValueError("metadata CSV missing required columns")
        for row in reader:
            opportunity_id = row.get("opportunity_id")
            sam_url = row.get("sam-url")
            if not opportunity_id or not sam_url:
                continue
            rows[opportunity_id] = row
    return rows


def _load_document_rows(doc_summaries_csv: Path) -> Dict[str, List[Dict[str, str]]]:
    grouped: Dict[str, List[Dict[str, str]]] = {}
    with doc_summaries_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if "opportunity_id" not in reader.fieldnames:
            raise ValueError("doc summaries CSV must include 'opportunity_id'")
        for row in reader:
            opportunity_id = row.get("opportunity_id")
            if not opportunity_id:
                continue
            grouped.setdefault(opportunity_id, []).append(row)
    return grouped

