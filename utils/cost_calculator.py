"""Cost calculation utilities for Gemini API calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Pricing for gemini-flash-lite-latest (as of Nov 2025)
# NOTE: Verify current pricing at https://ai.google.dev/pricing
# These are approximate rates - update based on actual Google pricing
# Typical rates: $0.075 per 1M input tokens, $0.30 per 1M output tokens
GEMINI_FLASH_LITE_INPUT_COST_PER_1K_TOKENS = 0.000075  # $0.075 per 1M tokens = $0.000075 per 1K tokens
GEMINI_FLASH_LITE_OUTPUT_COST_PER_1K_TOKENS = 0.0003  # $0.30 per 1M tokens = $0.0003 per 1K tokens


@dataclass
class CostStats:
    """Cost statistics for API calls."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    num_calls: int = 0

    def add_usage(self, input_tokens: int, output_tokens: int, cost_per_1k_input: Optional[float] = None, cost_per_1k_output: Optional[float] = None) -> None:
        """Add usage statistics and calculate costs."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += input_tokens + output_tokens
        self.num_calls += 1

        input_cost_per_1k = cost_per_1k_input or GEMINI_FLASH_LITE_INPUT_COST_PER_1K_TOKENS
        output_cost_per_1k = cost_per_1k_output or GEMINI_FLASH_LITE_OUTPUT_COST_PER_1K_TOKENS

        call_input_cost = (input_tokens / 1000.0) * input_cost_per_1k
        call_output_cost = (output_tokens / 1000.0) * output_cost_per_1k

        self.input_cost += call_input_cost
        self.output_cost += call_output_cost
        self.total_cost += call_input_cost + call_output_cost

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "input_cost": self.input_cost,
            "output_cost": self.output_cost,
            "total_cost": self.total_cost,
            "num_calls": self.num_calls,
        }


def estimate_tokens_from_text(text: str) -> int:
    """Estimate token count from text (rough approximation: ~4 chars per token)."""
    if not text:
        return 0
    # Rough approximation: tokens are typically ~4 characters
    # This is a conservative estimate
    return len(text) // 4


def calculate_cost_from_usage(
    input_tokens: int,
    output_tokens: int,
    model: str = "gemini-flash-lite-latest",
) -> tuple[float, float, float]:
    """Calculate costs from token usage.
    
    Returns: (input_cost, output_cost, total_cost)
    """
    # Get pricing based on model
    if "flash-lite" in model.lower():
        input_cost_per_1k = GEMINI_FLASH_LITE_INPUT_COST_PER_1K_TOKENS
        output_cost_per_1k = GEMINI_FLASH_LITE_OUTPUT_COST_PER_1K_TOKENS
    else:
        # Default to flash-lite pricing if unknown
        input_cost_per_1k = GEMINI_FLASH_LITE_INPUT_COST_PER_1K_TOKENS
        output_cost_per_1k = GEMINI_FLASH_LITE_OUTPUT_COST_PER_1K_TOKENS

    input_cost = (input_tokens / 1000.0) * input_cost_per_1k
    output_cost = (output_tokens / 1000.0) * output_cost_per_1k
    total_cost = input_cost + output_cost

    return input_cost, output_cost, total_cost

