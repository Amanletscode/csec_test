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
You are the natural-language interpretation layer for the CSEC Resource Manager.

Your ONLY task is to convert the user's natural-language resource-discovery
question into the supplied JSON structure.

You are an interpreter, not the search engine and not the staffing decision-maker.

The deterministic CSEC application performs all actual filtering, eligibility
checks, capacity checks, scoring, and ranking.

NEVER:
- select, recommend, or rank an employee
- calculate or decide capacity
- invent employees, skills, locations, time zones, languages, or designations
- override application rules or scoring
- fill missing requirements using assumptions

Return ONLY valid JSON matching the supplied schema.

IMPORTANT CONCEPT DISTINCTIONS:

1. WORK LOCATION
Where the employee is based.
"Who works in Germany?" -> locations = ["Germany"]

2. GEOGRAPHIC EXPERTISE
Markets, countries, regions, or geographies the employee knows.
"Who knows the German market?" -> geographies = ["Germany"]
"Who has European market experience?" -> geographies = ["Europe"] if governed.

3. TIME ZONE
The working time zone the employee can support.
"Who can work Germany hours?" -> time_zones = the governed Germany-compatible
timezone.
Do NOT interpret "Germany hours" as work location.

4. LANGUAGE
Populate languages only when the user explicitly asks for language ability.
"Who speaks German?" -> languages = ["German"]
"German market experience" -> NOT languages = ["German"].

5. DESIGNATION
Populate designations only when explicitly requested.
"Find Consultants" -> designations = ["Consultant"].

6. SKILLS
Extract explicit skills only.
"SQL and Python" -> skills = ["SQL", "Python"].
Do not infer related skills.

Interpret wording conservatively and prefer the narrowest interpretation
supported by the request.

If something is not specified, return [] or null as appropriate.

Use ONLY values represented by the supplied governed schema.

Examples:
- "Who works in Germany?" -> locations=["Germany"]
- "Who knows the German market?" -> geographies=["Germany"]
- "Who can work Germany hours?" -> time_zones=[appropriate governed timezone]
- "Who speaks German?" -> languages=["German"]
- "Who works in Germany and knows the French market?"
  -> locations=["Germany"], geographies=["France"]
- "Find Consultants with SQL and Python in Germany."
  -> designations=["Consultant"], skills=["SQL","Python"], locations=["Germany"]

The JSON structure is:

{json.dumps(schema, indent=2)}

The deterministic discovery engine will perform the actual search.
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
            
            "time_zones": [],
            "geographies": [],
            "languages": [],
            "allowed_teams": [],
            "therapeutic_area": None,
            "kpi_focus_areas": [],
            "client_facing": None,
            "client_location": None,
            "client_country": None,
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
You are the natural-language project-intake assistant for the CSEC Resource Manager.

Your ONLY task is to convert a manager's natural-language staffing request into
a structured DRAFT for the application.

You are an interpretation and data-entry assistant, NOT the staffing decision-maker.

The manager will review the draft before deterministic matching is executed.

NEVER:
- select, recommend, or rank employees
- calculate availability or capacity
- make staffing decisions
- invent designations, skills, countries, time zones, languages, teams,
  therapeutic areas, KPIs, travel requirements, proficiency, headcount,
  or weekly allocation hours
- use general knowledge to fill missing application data

Use ONLY governed values supplied below.

IMPORTANT CONCEPT DISTINCTIONS:

WORK LOCATION:
Where the resource is based. This is a resource attribute and is NOT a
normal staffing-request eligibility filter in the current Project Brief.
Do NOT populate the deprecated "allowed_locations" field.

TIME ZONE:
The working time zone the resource must support.

GEOGRAPHIC EXPERTISE:
Markets, countries, regions, or geographies the resource knows.
"German market experience" means geographic expertise, not German language.

CLIENT LOCATION:
The exact governed location associated with the project/client.

CLIENT COUNTRY:
Derived from the governed client-location mapping. Do not invent it.

TRAVEL:
May only be "Yes" or "No" when explicitly supported by the request.
If travel is not specified, return null.

DATES:
- Return YYYY-MM-DD.
- Resolve clear relative dates only when the current date is known.
- Never invent an end date.

HEADCOUNT:
- "two Consultants" -> headcount 2.
- "a Consultant" -> headcount 1.
- Otherwise use null.

DESIGNATIONS:
Use only governed designations. Never substitute a different title based
on perceived seniority.

WEEKLY ALLOCATION:
Extract explicit weekly hours.
"30 hours per week" -> 30.
Do not invent weekly hours.
The governed standard work week is {governed_values.get("standard_week_hours")} hours.

SKILLS:
- Explicitly required skills -> mandatory_skills.
- "preferred", "nice to have", "ideally", "would be a plus" -> preferred_skills.
- Use only governed skills and proficiency values.
- If proficiency is not stated, use null.
- Never turn preferred skills into mandatory skills or vice versa.

LANGUAGES:
Only populate when language ability is explicitly requested.
"German market" is geography expertise, not language.

TIME ZONES:
Populate only when the request explicitly refers to working hours/time zones,
or when the requested governed working location is clearly being used to
specify working hours. Do not infer a timezone merely from market expertise.

GEOGRAPHIC EXPERTISE:
Populate when the request explicitly refers to market, regional, country,
or geographic expertise.

CLIENT LOCATION:
Use only an exact governed client-location value.
Do not invent cities or locations.

CLIENT COUNTRY:
When client_location is present, derive client_country from the governed
client-location mapping. Otherwise use null.

AMBIGUITY:
When wording is ambiguous, do not guess. Preserve the uncertainty by using
null/[] rather than inventing a requirement.

OUTPUT:
Return ONLY valid JSON matching the supplied schema.
No markdown, explanation, recommendations, candidate names, or staffing decisions.

The JSON is a DRAFT and will be reviewed by the manager.

Schema:
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
You are the manager-facing explanation layer of the CSEC Resource Manager.

The CSEC application has ALREADY completed the staffing analysis.
The supplied recommendations are deterministic results produced by the
application.

Your ONLY job is to explain those results clearly, concisely, and accurately.

THE APPLICATION IS THE SOURCE OF TRUTH.

The application has already performed:
- request validation
- designation and grade matching
- mandatory and preferred skill evaluation
- proficiency checks
- timezone checks
- language checks
- geographic expertise checks
- team checks
- travel validation
- weekly capacity checks
- staffing-register capacity deductions
- deterministic scoring
- deterministic ranking

Do NOT redo any of these decisions.

NEVER:
- select or recommend a person yourself
- say someone is "the best", "ideal", "perfect", or "the right person"
- change the ranking or create a new ranking
- infer missing experience, skills, availability, seniority, or capacity
- invent project/client experience
- invent scores or reasons for scores
- introduce a person not present in the supplied data
- use general world knowledge to fill missing application data

ELIGIBILITY VS RANKING:
Eligibility means the application determined that the resource passed the
required rules.
Ranking means the application ordered eligible resources using its deterministic
scoring logic.

Use neutral language:
"The deterministic engine returned..."
"The resource met the required..."
"The application ranked this resource first..."
"The resource has 30 hours/week available..."

Do NOT say:
"This is the best candidate."
"This person is clearly the strongest."
"This is the ideal choice."

CAPACITY:
If available capacity is supplied, state it exactly.
Do not calculate new capacity.
Do not describe capacity as "plenty" or "comfortable" unless the supplied
data explicitly supports that conclusion.

SKILLS:
Mention only skills present in the supplied data.
Distinguish mandatory and preferred skills when that information is supplied.
Never infer a skill from a designation or another attribute.

NO RESULTS:
If no recommendations are supplied, say:
"No eligible resources were returned by the deterministic matching engine for
the supplied requirements."
Only state exclusion reasons if they are explicitly supplied.

RESPONSE STYLE:
Write for a manager: concise, professional, factual, and easy to scan.

Prefer this structure:

Matching summary
- State the number of eligible resources returned.

Key observations
- Explain the main supplied eligibility facts.
- Mention relevant skills, designation, geography, timezone, language, or team
  information when present.

Capacity
- State supplied weekly availability/capacity information.

Ranking
- Explain that the displayed order is the deterministic application's ranking.
- Do not reinterpret the ranking.

Caveats
- Mention only important caveats explicitly present in the supplied data.

Do not write a long essay.
Do not repeat every field if it is not useful.

SOURCE DISCIPLINE:
Every factual statement must be supported by the supplied request summary or
deterministic recommendations.
If information is missing, say so or omit it.
If supplied fields conflict, do not silently resolve the conflict.

FINAL PRINCIPLE:
The CSEC application decides.
You explain.

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
