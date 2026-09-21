from __future__ import annotations

import json
from typing import Any


# ---------------------------------------------------------------------------
# Application LLM configuration
# ---------------------------------------------------------------------------

# The Azure team confirmed that GPT-4o-mini is the model to use for now.
LLM_MODEL = "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Azure configuration
# ---------------------------------------------------------------------------

def _load_azure_config():
    """
    Load the IQVIA Azure OpenAI configuration only when an AI operation
    is requested.

    The CSEC application does not require the separate Azure API setup
    merely to start Streamlit.

    The Azure team's existing setup provides:

        configs/
            __init__.py
            constants.py
            deployments.py
    """

    try:
        import configs.constants as const
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "The IQVIA Azure OpenAI configuration package is not available "
            "in this Python environment. The Azure API setup containing "
            "'configs/constants.py' must be made available before AI can "
            "be used."
        ) from exc

    return const


def _configuration_available() -> bool:
    """
    Check whether the Azure team's configuration package is available.

    This is intentionally a lightweight check.

    It does NOT authenticate with Azure and does NOT make an API call.
    """

    try:
        const = _load_azure_config()
    except RuntimeError:
        return False

    required_settings = [
        "OPENAI_API_BASE",
        "OPENAI_API_TYPE",
        "OPENAI_ACCOUNT_NAME",
        "OPENAI_API_VERSION",
        "SCOPE_INTERACTIVE_BROWSER",
    ]

    return all(
        bool(getattr(const, setting, None))
        for setting in required_settings
    )


# ---------------------------------------------------------------------------
# Azure OpenAI adapter
# ---------------------------------------------------------------------------

class AzureLLMAdapter:
    """
    Optional Azure OpenAI adapter for the CSEC Resource Manager.

    The LLM is advisory only.

    The LLM may:
        - understand natural-language staffing requests
        - prepare a structured Project brief / Team & skills draft
        - interpret natural-language discovery requests
        - explain deterministic recommendations

    The LLM may NOT:
        - select resources
        - rank resources
        - calculate capacity
        - override eligibility rules
        - override designation or grade rules
        - override mandatory skills
        - modify deterministic scoring
        - confirm staffing allocations

    The existing CSEC deterministic application remains the
    source of truth.
    """

    def __init__(self):
        self._client = None

    # ------------------------------------------------------------------
    # Configuration status
    # ------------------------------------------------------------------

    @property
    def configured(self) -> bool:
        """
        Return True only when the Azure team's configuration package
        is available and contains the required settings.

        This does not authenticate or call Azure.
        """

        return _configuration_available()

    # ------------------------------------------------------------------
    # Azure client
    # ------------------------------------------------------------------

    def _get_client(self):
        """
        Create the Azure OpenAI client using the same authentication
        pattern provided by the Azure/OpenAI team.
        """

        const = _load_azure_config()

        try:
            from azure.identity import (
                InteractiveBrowserCredential,
                get_bearer_token_provider,
            )
        except ImportError as exc:
            raise RuntimeError(
                "The 'azure-identity' package is not installed in the "
                "Python environment running the CSEC application."
            ) from exc

        try:
            from openai import AzureOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "The 'openai' package is not installed in the "
                "Python environment running the CSEC application."
            ) from exc

        if self._client is not None:
            return self._client

        # --------------------------------------------------------------
        # This follows the Azure team's supplied code.py.
        # --------------------------------------------------------------

        token_provider = get_bearer_token_provider(
            InteractiveBrowserCredential(),
            const.SCOPE_INTERACTIVE_BROWSER,
        )

        azure_endpoint = (
            f"{const.OPENAI_API_BASE.rstrip('/')}"
            f"/{const.OPENAI_API_TYPE}"
            f"/{const.OPENAI_ACCOUNT_NAME}"
        )

        self._client = AzureOpenAI(
            azure_endpoint=azure_endpoint,
            azure_ad_token_provider=token_provider,
            api_version=const.OPENAI_API_VERSION,
        )

        return self._client

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _message_content(response) -> str:
        """
        Extract text from an Azure OpenAI chat completion response.
        """

        try:
            content = response.choices[0].message.content
        except Exception as exc:
            raise RuntimeError(
                "Azure OpenAI returned an unexpected response format."
            ) from exc

        if not content:
            raise RuntimeError(
                "Azure OpenAI returned an empty response."
            )

        return str(content).strip()

    @classmethod
    def _json_response(cls, response) -> dict[str, Any]:
        """
        Convert the model response into a JSON dictionary.
        """

        raw = cls._message_content(response)

        # Handle accidental markdown code fences.
        if raw.startswith("```"):
            raw = raw.replace("```json", "", 1)
            raw = raw.replace("```", "")
            raw = raw.strip()

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Azure OpenAI returned a response that was not valid JSON."
            ) from exc

        if not isinstance(payload, dict):
            raise RuntimeError(
                "Azure OpenAI returned JSON, but the result was not "
                "a JSON object."
            )

        return payload

    # ------------------------------------------------------------------
    # Natural-language discovery
    # ------------------------------------------------------------------

    def interpret(
        self,
        text: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Interpret a natural-language resource-discovery request.

        The deterministic discovery engine remains responsible for
        filtering and matching.
        """

        client = self._get_client()

        system_prompt = f"""
You are the natural-language interpretation layer for the
CSEC Resource Manager.

Your ONLY task is to convert the user's natural-language request
into the supplied JSON structure.

You are NOT the staffing decision-maker.

You MUST NOT:
- recommend a person
- rank people
- select an employee
- invent employees
- invent skills
- invent locations
- invent designations
- make capacity decisions
- override application rules
- change scoring

Return ONLY valid JSON.

The JSON structure is:

{json.dumps(schema, indent=2)}

Rules:

1. Use only values represented by the supplied governed schema.
2. If the user does not specify something, return null or [].
3. Do not guess missing requirements.
4. Interpret the user's wording conservatively.
5. The deterministic CSEC application performs all actual
   filtering, eligibility checks, capacity checks and ranking.
"""

        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": str(text or "").strip(),
                },
            ],
            max_tokens=1000,
            temperature=0.1,
        )

        return self._json_response(response)

    # ------------------------------------------------------------------
    # Natural-language staffing request
    # ------------------------------------------------------------------

    def draft_staffing_request(
        self,
        user_request: str,
        governed_values: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Convert a manager's natural-language staffing request into
        a structured draft.

        IMPORTANT:
        This is a DRAFT only.

        The user must review and edit the resulting Project brief
        and Team & skills information before matching is executed.
        """

        client = self._get_client()

        schema = {
            "project_name": None,
            "client": None,
            "project_description": None,
            "start_date": None,
            "end_date": None,
            "allowed_locations": [],
            "time_zones": [],
            "languages": [],
            "allowed_teams": [],
            "therapeutic_area": None,
            "kpi_focus_areas": [],
            "client_facing": None,
            "client_location": None,
            "travel_requirement": None,
            "roles": [
                {
                    "designation": None,
                    "headcount": None,
                    "allocation_hours": None,
                    "mandatory_skills": [
                        {
                            "skill": None,
                            "proficiency": None,
                        }
                    ],
                    "preferred_skills": [
                        {
                            "skill": None,
                            "proficiency": None,
                        }
                    ],
                }
            ],
        }

        system_prompt = f"""
You are the project-intake interpretation layer for the
CSEC Resource Manager.

Your task is ONLY to convert a manager's natural-language
staffing request into a structured DRAFT.

The manager will review the draft and can modify it before
the application performs any matching.

Do NOT make staffing decisions.

You MUST NOT:
- select employees
- recommend employees
- rank employees
- calculate availability
- calculate capacity
- make staffing decisions
- invent designations
- invent skills
- invent countries
- invent time zones
- invent languages
- invent teams
- invent therapeutic areas
- invent KPIs
- invent travel requirements
- invent proficiency values
- invent headcount
- invent weekly allocation hours

Use ONLY the governed values supplied below.

If the request does not specify a value:
- use null for a single value
- use [] for a list
- do not guess

DATES:
- Return dates as YYYY-MM-DD.
- Resolve clear relative dates using the current date.
- Do not invent an end date.

HEADCOUNT:
- "two Consultants" means headcount 2.
- "a Consultant" means headcount 1.
- Do not invent headcount.

WEEKLY ALLOCATION:
- Use explicit weekly hours when provided.
- Do not invent weekly hours.
- The standard work week is
  {governed_values.get("standard_week_hours")} hours.

SKILLS:
- Explicit required skills are mandatory skills.
- Words such as "preferred", "nice to have", "ideally",
  or "would be a plus" indicate preferred skills.
- Use only skills from the governed catalogue.
- Use only governed proficiency values.
- If proficiency is not stated, return null.

EXAMPLE STAFFING REQUESTS:

"We need two Consultants in India for a healthcare analytics
project starting 1 October 2026. They should have SQL and
Python as mandatory skills, while Power BI would be preferred.
Each person should be available for 30 hours per week."

"For a Germany-based project, we need one Senior Consultant
from 5 October through 20 December 2026. SQL is mandatory,
Python is preferred, and the person should work in the
appropriate Germany-compatible time zone."

"Please staff one Principal in India for 15 hours per week
from next month. The person needs Databricks as a mandatory
skill and GenAI experience would be preferred."

The examples demonstrate interpretation only. They are not
instructions to invent values for a different request.

Return ONLY valid JSON matching this structure:

{json.dumps(schema, indent=2)}

Governed values:

{json.dumps(governed_values, indent=2)}
"""

        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": str(user_request or "").strip(),
                },
            ],
            max_tokens=1800,
            temperature=0.1,
        )

        return self._json_response(response)

    # ------------------------------------------------------------------
    # Recommendation explanation
    # ------------------------------------------------------------------

    def summarize_recommendations(
        self,
        request_summary: dict[str, Any],
        recommendations: list[dict[str, Any]],
    ) -> str:
        """
        Explain already-computed deterministic recommendations.

        The LLM does not re-rank or alter the recommendations.
        """

        client = self._get_client()

        safe_recommendations = recommendations[:5]

        system_prompt = """
You are an explanation layer for the CSEC Resource Manager.

The CSEC application has ALREADY performed:
- eligibility checks
- designation and grade checks
- skill checks
- location checks
- timezone checks
- language checks
- capacity checks
- scoring
- ranking

You MUST NOT redo or change those decisions.

Explain the supplied deterministic results in concise,
manager-friendly language.

Rules:
- Do not introduce a person not present in the supplied data.
- Do not change the ranking.
- Do not re-rank candidates.
- Do not invent skills.
- Do not invent availability.
- Do not invent experience.
- Do not invent scores.
- Do not make claims unsupported by the supplied data.
- If no candidates are supplied, say that no eligible candidates
  were returned.
- State that the application's deterministic matching engine
  performed the eligibility and ranking.

Return plain text only.
"""

        user_payload = {
            "request": request_summary,
            "deterministic_recommendations": safe_recommendations,
        }

        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        user_payload,
                        default=str,
                    ),
                },
            ],
            max_tokens=1000,
            temperature=0.1,
        )

        return self._message_content(response)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_azure_llm_adapter() -> AzureLLMAdapter:
    """
    Create the optional Azure LLM adapter.

    Creating the adapter does NOT:
        - authenticate
        - open a browser
        - call Azure
        - call GPT-4o-mini

    Those things happen only when an actual AI operation is requested.
    """

    return AzureLLMAdapter()
