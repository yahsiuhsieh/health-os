from __future__ import annotations

import urllib.error
from dataclasses import dataclass
from typing import Any

from healthos.coach import CoachDraft, parse_coach_draft, prompt_text, rule_based_coach_draft
from healthos.config import Settings
from healthos.http_client import HttpError, JsonHttpClient


@dataclass(frozen=True)
class DraftGenerationResult:
    draft: CoachDraft
    provider: str
    model: str


class OpenAIClient:
    def __init__(self, settings: Settings, http: JsonHttpClient) -> None:
        self.settings = settings
        self.http = http

    def generate_draft(self, payload: dict[str, Any], *, instructions: str) -> DraftGenerationResult:
        response = self.http.request(
            "POST",
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json_body={
                "model": self.settings.openai_model,
                "instructions": instructions,
                "input": prompt_text(payload),
                "max_output_tokens": self.settings.ai_max_output_tokens,
                "store": False,
            },
        )
        output_text = self._extract_output_text(response)
        if not output_text:
            raise RuntimeError(f"OpenAI response did not include output text: {response}")
        return DraftGenerationResult(
            draft=parse_coach_draft(output_text, payload),
            provider="openai",
            model=str(response.get("model") or self.settings.openai_model),
        )

    def _extract_output_text(self, response: dict[str, Any]) -> str:
        if isinstance(response.get("output_text"), str):
            return response["output_text"]
        chunks: list[str] = []
        for item in response.get("output", []):
            if not isinstance(item, dict):
                continue
            content_items = item.get("content", [])
            if not isinstance(content_items, list):
                continue
            for content in content_items:
                if isinstance(content, dict) and content.get("type") == "output_text" and content.get("text"):
                    chunks.append(content["text"])
        return "\n".join(chunks)


class OpenRouterClient:
    def __init__(self, settings: Settings, http: JsonHttpClient) -> None:
        self.settings = settings
        self.http = http

    def generate_draft(self, payload: dict[str, Any], *, instructions: str) -> DraftGenerationResult:
        response = self.http.request(
            "POST",
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.settings.openrouter_api_key}",
                "Content-Type": "application/json",
                "X-OpenRouter-Title": "HealthOS",
            },
            json_body={
                "model": self.settings.openrouter_model,
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": prompt_text(payload)},
                ],
                "max_tokens": self.settings.ai_max_output_tokens,
            },
        )
        output_text = self._extract_message_content(response)
        if not output_text:
            raise RuntimeError(f"OpenRouter response did not include message content: {response}")
        return DraftGenerationResult(
            draft=parse_coach_draft(output_text, payload),
            provider="openrouter",
            model=str(response.get("model") or self.settings.openrouter_model),
        )

    def _extract_message_content(self, response: dict[str, Any]) -> str:
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return ""
        message = first_choice.get("message", {})
        if not isinstance(message, dict):
            return ""
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    chunks.append(item["text"])
            return "\n".join(chunks)
        return ""


class RuleBasedClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate_draft(self, payload: dict[str, Any], *, instructions: str | None = None) -> DraftGenerationResult:
        return DraftGenerationResult(
            draft=rule_based_coach_draft(payload),
            provider="rule_based",
            model="rule-based",
        )


class AIClient:
    def __init__(self, settings: Settings, http: JsonHttpClient) -> None:
        self.settings = settings
        self.openai = OpenAIClient(settings, http)
        self.openrouter = OpenRouterClient(settings, http)
        self.rule_based = RuleBasedClient(settings)

    def generate_draft(self, payload: dict[str, Any], *, instructions: str) -> DraftGenerationResult:
        if self.settings.ai_provider == "rule_based":
            return self.rule_based.generate_draft(payload, instructions=instructions)
        if self.settings.ai_provider == "openai":
            return self.openai.generate_draft(payload, instructions=instructions)
        if self.settings.ai_provider == "openrouter":
            return self._generate_with_openrouter_fallback(payload, instructions=instructions)
        raise ValueError(f"Unsupported AI_PROVIDER: {self.settings.ai_provider}")

    def _generate_with_openrouter_fallback(
        self,
        payload: dict[str, Any],
        *,
        instructions: str,
    ) -> DraftGenerationResult:
        if not self.settings.openrouter_api_key:
            return self.rule_based.generate_draft(payload, instructions=instructions)
        try:
            return self.openrouter.generate_draft(payload, instructions=instructions)
        except (HttpError, RuntimeError, TimeoutError, ValueError, urllib.error.URLError):
            return self.rule_based.generate_draft(payload, instructions=instructions)
