"""Generate cost reports for LLM calls in each run."""

from __future__ import annotations

import argparse
import csv
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from utils.cost_calculator import (
    CostStats,
    estimate_tokens_from_text,
    calculate_cost_from_usage,
)


LOGGER = logging.getLogger(__name__)


@dataclass
class RunCostSummary:
    """Cost summary for a single run."""
    run_name: str
    run_path: Path
    doc_summaries: CostStats
    opportunity_summaries: CostStats
    total: CostStats

    def to_markdown(self) -> str:
        """Generate markdown representation of the cost summary."""
        lines = []
        lines.append(f"## {self.run_name}")
        lines.append("")
        lines.append(f"**Run Path:** `{self.run_path}`")
        lines.append("")
        
        # Document Summaries
        lines.append("### Document Summaries")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Total Calls | {self.doc_summaries.num_calls:,} |")
        lines.append(f"| Input Tokens | {self.doc_summaries.input_tokens:,} |")
        lines.append(f"| Output Tokens | {self.doc_summaries.output_tokens:,} |")
        lines.append(f"| Total Tokens | {self.doc_summaries.total_tokens:,} |")
        lines.append(f"| Input Cost | ${self.doc_summaries.input_cost:.6f} |")
        lines.append(f"| Output Cost | ${self.doc_summaries.output_cost:.6f} |")
        lines.append(f"| **Total Cost** | **${self.doc_summaries.total_cost:.6f}** |")
        lines.append("")
        
        # Opportunity Summaries
        lines.append("### Opportunity Summaries")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Total Calls | {self.opportunity_summaries.num_calls:,} |")
        lines.append(f"| Input Tokens | {self.opportunity_summaries.input_tokens:,} |")
        lines.append(f"| Output Tokens | {self.opportunity_summaries.output_tokens:,} |")
        lines.append(f"| Total Tokens | {self.opportunity_summaries.total_tokens:,} |")
        lines.append(f"| Input Cost | ${self.opportunity_summaries.input_cost:.6f} |")
        lines.append(f"| Output Cost | ${self.opportunity_summaries.output_cost:.6f} |")
        lines.append(f"| **Total Cost** | **${self.opportunity_summaries.total_cost:.6f}** |")
        lines.append("")
        
        # Overall Summary
        lines.append("### Overall Summary")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Total Calls | {self.total.num_calls:,} |")
        lines.append(f"| Total Input Tokens | {self.total.input_tokens:,} |")
        lines.append(f"| Total Output Tokens | {self.total.output_tokens:,} |")
        lines.append(f"| Total Tokens | {self.total.total_tokens:,} |")
        lines.append(f"| Total Input Cost | ${self.total.input_cost:.6f} |")
        lines.append(f"| Total Output Cost | ${self.total.output_cost:.6f} |")
        lines.append(f"| **Grand Total Cost** | **${self.total.total_cost:.6f}** |")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        return "\n".join(lines)


def estimate_costs_from_doc_summaries_csv(csv_path: Path, model: str) -> CostStats:
    """Estimate costs from document summaries CSV by analyzing text length."""
    stats = CostStats()
    
    if not csv_path.exists():
        LOGGER.warning("Document summaries CSV not found: %s", csv_path)
        return stats
    
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                summary = row.get("summary", "")
                if not summary or row.get("error"):
                    continue
                
                # Estimate tokens from summary length
                # We need to estimate input tokens too - use a conservative estimate
                # For document summaries, input is typically much larger than output
                # Estimate based on typical prompt + document content
                estimated_output_tokens = estimate_tokens_from_text(summary)
                # Rough estimate: input is 5-10x output for document summaries
                estimated_input_tokens = estimated_output_tokens * 7
                
                stats.add_usage(estimated_input_tokens, estimated_output_tokens)
    except Exception as exc:
        LOGGER.exception("Error reading document summaries CSV %s: %s", csv_path, exc)
    
    return stats


def estimate_costs_from_opportunity_summaries_csv(csv_path: Path, model: str) -> CostStats:
    """Estimate costs from opportunity summaries CSV by analyzing text length."""
    stats = CostStats()
    
    if not csv_path.exists():
        LOGGER.warning("Opportunity summaries CSV not found: %s", csv_path)
        return stats
    
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                long_summary = row.get("govbeacon-long-summary", "")
                short_summary = row.get("govbeacon-short-summary", "")
                
                if not long_summary or row.get("error"):
                    continue
                
                # Combine long and short summaries for output token estimate
                combined_output = f"{long_summary}\n\n{short_summary}"
                estimated_output_tokens = estimate_tokens_from_text(combined_output)
                
                # For opportunity summaries, input includes metadata + doc summaries
                # Estimate input as 3-5x output
                estimated_input_tokens = estimated_output_tokens * 4
                
                stats.add_usage(estimated_input_tokens, estimated_output_tokens)
    except Exception as exc:
        LOGGER.exception("Error reading opportunity summaries CSV %s: %s", csv_path, exc)
    
    return stats


def load_usage_from_json(json_path: Path) -> Optional[CostStats]:
    """Load usage statistics from a JSON file."""
    if not json_path.exists():
        return None
    
    try:
        with json_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
            stats = CostStats()
            for entry in data.get("calls", []):
                input_tokens = entry.get("input_tokens", 0)
                output_tokens = entry.get("output_tokens", 0)
                stats.add_usage(input_tokens, output_tokens)
            return stats
    except Exception as exc:
        LOGGER.exception("Error reading usage JSON %s: %s", json_path, exc)
        return None


def analyze_run(run_path: Path) -> Optional[RunCostSummary]:
    """Analyze a single run directory and calculate costs."""
    run_name = run_path.name
    
    # Find document summaries CSV (most recent)
    doc_summaries_dir = run_path / "doc_summaries"
    doc_summaries_csv = None
    if doc_summaries_dir.exists():
        csv_files = sorted(doc_summaries_dir.glob("doc-summaries-*.csv"), reverse=True)
        if csv_files:
            doc_summaries_csv = csv_files[0]
    
    # Find opportunity summaries CSV (most recent)
    opp_summaries_dir = run_path / "opportunity_summaries"
    opp_summaries_csv = None
    if opp_summaries_dir.exists():
        csv_files = sorted(opp_summaries_dir.glob("sam-summary-*.csv"), reverse=True)
        if csv_files:
            opp_summaries_csv = csv_files[0]
    
    # Check for usage JSON files (future tracking)
    doc_usage_json = doc_summaries_dir / "usage.json" if doc_summaries_dir.exists() else None
    opp_usage_json = opp_summaries_dir / "usage.json" if opp_summaries_dir.exists() else None
    
    # Load or estimate costs
    doc_stats = CostStats()
    if doc_usage_json and doc_usage_json.exists():
        loaded = load_usage_from_json(doc_usage_json)
        if loaded:
            doc_stats = loaded
    elif doc_summaries_csv:
        # Extract model from filename or CSV
        model = "gemini-flash-lite-latest"
        if doc_summaries_csv:
            # Try to extract model from filename
            parts = doc_summaries_csv.stem.split("-")
            if len(parts) > 2:
                model = "-".join(parts[2:-1])  # Skip "doc" and "summaries" and timestamp
        doc_stats = estimate_costs_from_doc_summaries_csv(doc_summaries_csv, model)
    
    opp_stats = CostStats()
    if opp_usage_json and opp_usage_json.exists():
        loaded = load_usage_from_json(opp_usage_json)
        if loaded:
            opp_stats = loaded
    elif opp_summaries_csv:
        model = "gemini-flash-lite-latest"
        if opp_summaries_csv:
            parts = opp_summaries_csv.stem.split("-")
            if len(parts) > 2:
                model = "-".join(parts[2:-1])
        opp_stats = estimate_costs_from_opportunity_summaries_csv(opp_summaries_csv, model)
    
    # Skip runs with no data
    if doc_stats.num_calls == 0 and opp_stats.num_calls == 0:
        return None
    
    # Calculate totals
    total_stats = CostStats()
    total_stats.input_tokens = doc_stats.input_tokens + opp_stats.input_tokens
    total_stats.output_tokens = doc_stats.output_tokens + opp_stats.output_tokens
    total_stats.total_tokens = doc_stats.total_tokens + opp_stats.total_tokens
    total_stats.input_cost = doc_stats.input_cost + opp_stats.input_cost
    total_stats.output_cost = doc_stats.output_cost + opp_stats.output_cost
    total_stats.total_cost = doc_stats.total_cost + opp_stats.total_cost
    total_stats.num_calls = doc_stats.num_calls + opp_stats.num_calls
    
    return RunCostSummary(
        run_name=run_name,
        run_path=run_path,
        doc_summaries=doc_stats,
        opportunity_summaries=opp_stats,
        total=total_stats,
    )


def generate_cost_report(outputs_dir: Path, output_file: Optional[Path] = None) -> None:
    """Generate cost report for all runs in the outputs directory."""
    if not outputs_dir.exists():
        LOGGER.error("Outputs directory does not exist: %s", outputs_dir)
        return
    
    # Find all run directories
    run_dirs = [d for d in outputs_dir.iterdir() if d.is_dir()]
    
    if not run_dirs:
        LOGGER.warning("No run directories found in %s", outputs_dir)
        return
    
    # Analyze each run
    summaries: List[RunCostSummary] = []
    for run_dir in sorted(run_dirs):
        summary = analyze_run(run_dir)
        if summary:
            summaries.append(summary)
    
    if not summaries:
        LOGGER.warning("No runs with cost data found")
        return
    
    # Generate markdown report
    lines = []
    lines.append("# LLM Cost Report")
    lines.append("")
    lines.append(f"Generated for runs in: `{outputs_dir}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    
    # Overall totals
    overall_total = CostStats()
    for summary in summaries:
        overall_total.input_tokens += summary.total.input_tokens
        overall_total.output_tokens += summary.total.output_tokens
        overall_total.total_tokens += summary.total.total_tokens
        overall_total.input_cost += summary.total.input_cost
        overall_total.output_cost += summary.total.output_cost
        overall_total.total_cost += summary.total.total_cost
        overall_total.num_calls += summary.total.num_calls
    
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total Runs | {len(summaries)} |")
    lines.append(f"| Total Calls | {overall_total.num_calls:,} |")
    lines.append(f"| Total Input Tokens | {overall_total.input_tokens:,} |")
    lines.append(f"| Total Output Tokens | {overall_total.output_tokens:,} |")
    lines.append(f"| Total Tokens | {overall_total.total_tokens:,} |")
    lines.append(f"| Total Input Cost | ${overall_total.input_cost:.6f} |")
    lines.append(f"| Total Output Cost | ${overall_total.output_cost:.6f} |")
    lines.append(f"| **Grand Total Cost** | **${overall_total.total_cost:.6f}** |")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Per-run details
    lines.append("## Per-Run Details")
    lines.append("")
    
    for summary in summaries:
        lines.append(summary.to_markdown())
    
    # Write report
    report_content = "\n".join(lines)
    
    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("w", encoding="utf-8") as handle:
            handle.write(report_content)
        LOGGER.info("Cost report written to %s", output_file)
    else:
        print(report_content)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate cost reports for LLM calls")
    parser.add_argument(
        "--outputs-dir",
        type=Path,
        default=Path("outputs"),
        help="Path to outputs directory containing run directories",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to output markdown file (default: stdout)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Increase logging verbosity",
    )
    
    args = parser.parse_args()
    
    # Configure logging
    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)8s | %(name)s | %(message)s",
    )
    
    generate_cost_report(args.outputs_dir, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

