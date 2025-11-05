"""Wrapper around the Google Gemini API with retries and sane defaults."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional, Union, Tuple

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from .env import load_env_settings, require_env


LOGGER = logging.getLogger(__name__)


@dataclass
class GeminiSettings:
    model: str = "gemini-flash-lite-latest"
    temperature: float = 0.0
    top_p: float = 0.95
    top_k: int = 32
    max_output_tokens: Optional[int] = None  # No limit
    thinking_budget: int = 0


@dataclass
class UsageStats:
    """Usage statistics from a Gemini API call."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


class GeminiClient:
    """Lightweight synchronous client with retry logic."""

    def __init__(self, settings: GeminiSettings) -> None:
        load_env_settings()
        api_key = require_env("GEMINI_API_KEY")
        self._client = genai.Client(api_key=api_key)
        self._settings = settings

    def generate_text(
        self,
        *,
        user_text: str,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
    ) -> str:
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=user_text)])]
        config = self._build_config(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

        LOGGER.debug("Calling Gemini model=%s", self._settings.model)
        response_text, _ = self._generate_with_retry(contents, config)
        return response_text.strip()

    def generate_text_with_usage(
        self,
        *,
        user_text: str,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
    ) -> Tuple[str, UsageStats]:
        """Generate text and return usage statistics."""
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=user_text)])]
        config = self._build_config(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

        LOGGER.debug("Calling Gemini model=%s", self._settings.model)
        response_text, usage = self._generate_with_retry(contents, config)
        return response_text.strip(), usage

    def generate_from_parts(
        self,
        *,
        parts: Iterable[Union[str, types.Part]],
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
    ) -> str:
        content_parts: list[types.Part] = []
        for part in parts:
            if isinstance(part, types.Part):
                content_parts.append(part)
            else:
                content_parts.append(types.Part.from_text(text=str(part)))
        contents = [types.Content(role="user", parts=content_parts)]
        config = self._build_config(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

        LOGGER.debug("Calling Gemini model=%s with %s parts", self._settings.model, len(content_parts))
        response_text, _ = self._generate_with_retry(contents, config)
        return response_text.strip()

    def generate_from_parts_with_usage(
        self,
        *,
        parts: Iterable[Union[str, types.Part]],
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
    ) -> Tuple[str, UsageStats]:
        """Generate from parts and return usage statistics."""
        content_parts: list[types.Part] = []
        for part in parts:
            if isinstance(part, types.Part):
                content_parts.append(part)
            else:
                content_parts.append(types.Part.from_text(text=str(part)))
        contents = [types.Content(role="user", parts=content_parts)]
        config = self._build_config(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

        LOGGER.debug("Calling Gemini model=%s with %s parts", self._settings.model, len(content_parts))
        response_text, usage = self._generate_with_retry(contents, config)
        return response_text.strip(), usage

    def _build_config(
        self,
        *,
        system_instruction: Optional[str],
        temperature: Optional[float],
        max_output_tokens: Optional[int],
    ) -> types.GenerateContentConfig:
        # Build config without max_output_tokens to allow unlimited generation
        config_kwargs = {
            "temperature": temperature if temperature is not None else self._settings.temperature,
            "top_p": self._settings.top_p,
            "top_k": self._settings.top_k,
        }
        
        # Only add max_output_tokens if explicitly provided (not recommended)
        final_max_tokens = max_output_tokens if max_output_tokens is not None else self._settings.max_output_tokens
        if final_max_tokens is not None:
            config_kwargs["max_output_tokens"] = final_max_tokens
        
        config = types.GenerateContentConfig(**config_kwargs)

        if system_instruction:
            config.system_instruction = system_instruction

        if self._settings.thinking_budget is not None:
            config.thinking_config = types.ThinkingConfig(
                thinking_budget=self._settings.thinking_budget
            )

        return config

    @retry(wait=wait_exponential_jitter(initial=1, max=10), stop=stop_after_attempt(5))
    def _generate_with_retry(
        self,
        contents: list[types.Content],
        config: types.GenerateContentConfig,
    ) -> Tuple[str, UsageStats]:
        text_chunks: list[str] = []
        usage = UsageStats()
        try:
            for chunk in self._client.models.generate_content_stream(
                model=self._settings.model,
                contents=contents,
                config=config,
            ):
                if chunk.text:
                    text_chunks.append(chunk.text)
                # Capture usage statistics from the last chunk (which typically contains usage info)
                if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                    usage.input_tokens = getattr(chunk.usage_metadata, 'prompt_token_count', 0) or 0
                    usage.output_tokens = getattr(chunk.usage_metadata, 'candidates_token_count', 0) or 0
                    usage.total_tokens = getattr(chunk.usage_metadata, 'total_token_count', 0) or 0
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("Gemini request failed: %s", exc)
            raise

        return "".join(text_chunks), usage

