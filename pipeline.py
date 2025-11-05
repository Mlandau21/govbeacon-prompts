"""Command-line entry point for the GovBeacon SAM.gov processing pipeline."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Callable, Optional

from utils import load_env_settings


def _parse_path(path_str: str) -> Path:
    return Path(path_str).expanduser().resolve()


def _configure_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)8s | %(name)s | %(message)s",
    )


def _add_scrape_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "scrape",
        help="Scrape SAM.gov metadata and attachments for URLs in the input CSV",
    )
    parser.add_argument("--input", type=_parse_path, required=True, help="Path to input.csv containing sam-url values")
    parser.add_argument("--out", type=_parse_path, required=True, help="Output directory root (timestamped artifacts are created inside)")
    parser.add_argument("--login", action="store_true", help="Open a visible browser to refresh the SAM.gov session before scraping")
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of opportunities to process (for testing)")
    parser.add_argument("--concurrency", type=int, default=2, help="Max concurrent page loads/downloads")
    parser.set_defaults(handler=_run_scrape)


def _add_summarize_docs_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "summarize-docs",
        help="Generate document summaries for downloaded attachments",
    )
    parser.add_argument("--attachments", type=_parse_path, required=True, help="Path to attachments directory produced by the scraper")
    parser.add_argument("--metadata", type=_parse_path, required=False, help="Optional path to sam-metadata.csv for manifest context")
    parser.add_argument("--out", type=_parse_path, required=True, help="Output directory root (writes doc summaries CSV and manifests)")
    parser.add_argument("--model", type=str, default="gemini-flash-lite-latest", help="Gemini model name to use")
    parser.add_argument("--run-id", type=str, default=None, help="Optional run identifier to embed in outputs")
    parser.add_argument("--max-workers", type=int, default=2, help="Max parallel Gemini requests")
    parser.add_argument("--skip-existing", action="store_true", help="Skip files that already have summaries in the latest CSV")
    parser.set_defaults(handler=_run_summarize_docs)


def _add_summarize_opps_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "summarize-opps",
        help="Generate opportunity summaries from metadata and document summaries",
    )
    parser.add_argument("--metadata", type=_parse_path, required=True, help="Path to sam-metadata.csv produced by the scraper")
    parser.add_argument("--doc-summaries", type=_parse_path, required=True, help="Path to doc-summaries CSV to incorporate")
    parser.add_argument("--out", type=_parse_path, required=True, help="Output directory root (writes sam-summary CSV)")
    parser.add_argument("--model", type=str, default="gemini-flash-lite-latest", help="Gemini model name to use")
    parser.add_argument("--run-id", type=str, default=None, help="Optional run identifier to embed in outputs")
    parser.add_argument("--max-workers", type=int, default=2, help="Max parallel Gemini requests")
    parser.set_defaults(handler=_run_summarize_opps)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GovBeacon SAM.gov processing pipeline")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase logging verbosity (-v info, -vv debug)")

    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_scrape_parser(subparsers)
    _add_summarize_docs_parser(subparsers)
    _add_summarize_opps_parser(subparsers)

    return parser


def _invoke_handler(args: argparse.Namespace) -> None:
    handler: Optional[Callable[[argparse.Namespace], None]] = getattr(args, "handler", None)
    if handler is None:
        raise ValueError("No handler configured for command")
    handler(args)


def _run_scrape(args: argparse.Namespace) -> None:
    from scrape_sam import scrape_opportunities

    scrape_opportunities(
        input_csv=args.input,
        output_dir=args.out,
        require_login=args.login,
        limit=args.limit,
        concurrency=args.concurrency,
    )


def _run_summarize_docs(args: argparse.Namespace) -> None:
    from summarize_docs import summarize_documents

    summarize_documents(
        attachments_dir=args.attachments,
        output_dir=args.out,
        metadata_csv=args.metadata,
        model=args.model,
        run_id=args.run_id,
        max_workers=args.max_workers,
        skip_existing=args.skip_existing,
    )


def _run_summarize_opps(args: argparse.Namespace) -> None:
    from summarize_opportunities import summarize_opportunities

    summarize_opportunities(
        metadata_csv=args.metadata,
        doc_summaries_csv=args.doc_summaries,
        output_dir=args.out,
        model=args.model,
        run_id=args.run_id,
        max_workers=args.max_workers,
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)
    load_env_settings()

    _invoke_handler(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

