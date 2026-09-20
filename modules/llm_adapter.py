from __future__ import annotations

import json
import os
from typing import Any


class AzureLLMAdapter:
    """
    Optional Azure OpenAI adapter for natural-language interpretation.

    IMPORTANT:
    This adapter does NOT perform resource matching.
    It only converts natural language into a structured payload.

    The existing deterministic application remains responsible for:
    - eligibility
    - capacity
    - location
    - timezone
    - designation
    - skills
    - scoring
    - recommendations
    """

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        deployment: str | None = None,
    ):
        self.endpoint = (
            endpoint
            or os.getenv("AZURE_OPENAI_ENDPOINT")
            or ""
        ).strip()

        self.api_key = (
            api_key
            or os.getenv("AZURE_OPENAI_API_KEY")
            or ""
        ).strip()

        self.deployment = (
            deployment
            or os.getenv("AZURE_OPENAI_DEPLOYMENT")
            or ""
        ).strip()

        self._client = None

    @property
    def configured(self) -> bool:
        return bool(
            self.endpoint
            and self.api_key
            and self.deployment
        )

    def _get_client(self):
        if not self.configured:
            raise RuntimeError(
                "Azure OpenAI is not configured. "
                "Set AZURE_OPENAI_ENDPOINT, "
                "AZURE_OPENAI_API_KEY and "
                "AZURE_OPENAI_DEPLOYMENT."
            )

        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "The 'openai' package is not installed."
                ) from exc

            base_url = (
                self.endpoint.rstrip("/")
                + "/openai/v1/"
            )

            self._client = OpenAI(
                api_key=self.api_key,
                base_url=base_url,
            )

        return self._client

    @staticmethod
    def _system_prompt(schema: dict[str, Any]) -> str:
        return f"""
You are the natural-language interpretation layer
for an enterprise resource discovery application.

Your ONLY job is to interpret the user's request.

You MUST NOT:
- recommend a person
- rank employees
- invent employees
- invent skills
- invent locations
- invent designations
- override business rules
- make capacity decisions
- make staffing decisions

Return ONLY valid JSON.

The JSON must follow this schema:

{json.dumps(schema, indent=2)}

Rules:

1. Use only values present in the supplied governed lists.
2. If the user does not specify a field, return an empty
   list or null as appropriate.
3. Do not guess missing requirements.
4. Keep the interpretation conservative.
5. Availability expressed in hours must be converted to
   percentage using a 42.5 hour standard work week.

Examples:

"20 hours available"
means:

availability_min =
20 / 42.5 * 100

"Consultant in India"
means:

designations = ["Consultant"]
locations = ["India"]

"someone who knows SQL and Python"
means:

skills = ["SQL", "Python"]

The deterministic application will perform the actual search.
"""

    def interpret(
        self,
        text: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:

        client = self._get_client()

        prompt = self._system_prompt(schema)

        response = client.responses.create(
            model=self.deployment,
            instructions=prompt,
            input=str(text or "").strip(),
            max_output_tokens=800,
        )

        raw = getattr(response, "output_text", "")

        if not raw:
            raise RuntimeError(
                "Azure OpenAI returned an empty response."
            )

        raw = raw.strip()

        # Defensive handling if the model accidentally
        # surrounds JSON with markdown fences.
        if raw.startswith("```"):
            raw = raw.replace("```json", "", 1)
            raw = raw.replace("```", "")
            raw = raw.strip()

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Azure OpenAI returned invalid JSON."
            ) from exc

        if not isinstance(payload, dict):
            raise RuntimeError(
                "Azure OpenAI response must be a JSON object."
            )

        return payload


def build_azure_llm_adapter() -> AzureLLMAdapter:
    """
    Convenience factory.

    Returns an adapter even when Azure is not configured.
    The application can inspect .configured before using it.
    """
    return AzureLLMAdapter()