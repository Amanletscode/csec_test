from __future__ import annotations

from datetime import date, timedelta
import html
import textwrap
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import hashlib
import json

from modules.config import (
    DATA_VERSION,
    DEFAULT_WEIGHTS,
    DESIGNATIONS,
    DESIGNATION_TO_GRADE,
    KPI_FOCUS_AREAS,
    GEOGRAPHIES,
    CLIENT_LOCATION_TO_COUNTRY,
    LANGUAGES,
    PROFICIENCY,
    PROFICIENCY_LABELS,
    SKILL_CATALOG,
    STANDARD_WEEK_HOURS,
    THERAPEUTIC_AREAS,
    TIME_ZONES,
    TRAVEL_REQUIREMENTS,
)
from modules.data import (
    canonicalize_resources,
    dataset_health,
    load_workbook,
)
from modules.capacity import build_weekly_capacity
from modules.discovery import discovery_search
from modules.engine import build_near_matches, run_matching
from modules.records import (
    ALLOCATION_COLUMNS,
    OPPORTUNITY_COLUMNS,
    append_confirmed_allocations,
    load_register,
)
from modules.sample_data import write_demo_data
from modules.validation import parse_skill_string, validate_request
from modules.llm_adapter import build_azure_llm_adapter


st.set_page_config(
    page_title="CSEC Resource Manager",
    page_icon="◫",
    layout="wide",
    initial_sidebar_state="collapsed",
)

DATA_DIR = Path(__file__).parent / "data"
REGISTER_PATH = DATA_DIR / "staffing_register.xlsx"
DATA_DIR.mkdir(exist_ok=True)
if not (DATA_DIR / "resources.csv").exists():
    write_demo_data(DATA_DIR)

WORKFLOW_PAGES = ["Project Details", "Team & skills", "Recommendations"]
TOOL_PAGES = ["Capacity & risk", "Ask Copilot"]
PAGES = WORKFLOW_PAGES + TOOL_PAGES
NAV_LABELS = {
    "Project Details": "Staffing Request",
    "Team & skills": "Resource Requirements",
    "Recommendations": "Resource Matches",
    "Capacity & risk": "Capacity Assessment",
    "Ask Copilot": "Ask Copilot",
}
NAV_HELP = {
    "Project Details": "Define engagement context, delivery period, allocation needs and staffing constraints.",
    "Team & skills": "Define roles, headcount, capabilities, proficiency and recommendation criteria.",
    "Recommendations": "Review eligible resources ranked by capability alignment, availability and staffing fit.",
    "Capacity & risk": "Review availability, existing commitments, allocation feasibility and staffing risk.",
    "Ask Copilot": "Get AI-assisted explanations, alternatives and reviewable staffing actions.",
}


@st.cache_data(max_entries=3)
def load_cached_resources(data_dir: str, data_version: str):
    del data_version

    resources_path = Path(data_dir) / "resources.csv"

    resources = pd.read_csv(resources_path)

    return canonicalize_resources(resources)

def active_resources() -> pd.DataFrame:
    if st.session_state.uploaded_data is not None:
        return st.session_state.uploaded_data

    return load_cached_resources(
        str(DATA_DIR),
        DATA_VERSION,
    )

def capacity_horizon() -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Return the rolling planning horizon used to derive weekly capacity.

    The application maintains a 30-week planning horizon so that
    matching and capacity assessment have a consistent forward-looking view.
    """
    today = pd.Timestamp(date.today())

    start = today - pd.Timedelta(days=int(today.weekday()), unit="D")
    end = start + pd.Timedelta(weeks=29)

    return start.normalize(), end.normalize()

def apply_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
            --ink:#253746; --muted:#607582; --line:#D7E2E8;
            --brand:#005487; --brand-dark:#003B61; --accent:#00A1DF;
            --accent-dark:#0089BE; --soft:#F5F8FA; --pale:#EAF5FA;
            --ok:#16806a; --risk:#a4442c;
        }
        html, body, [class*="css"], [data-testid="stAppViewContainer"], [data-testid="stHeader"], button, input, textarea, select {
            font-family: "Inter", "Segoe UI", -apple-system, BlinkMacSystemFont, sans-serif !important;
        }
        .block-container {max-width:1420px; padding-top:5.0rem; padding-bottom:3.5rem;}
        h1, h2, h3, h4, h5, h6 {color:var(--ink); letter-spacing:-.015em; font-family:"Inter", "Segoe UI", -apple-system, BlinkMacSystemFont, sans-serif !important;}
        .brandbar {position:relative; z-index:5; display:flex; margin-top:.35rem; justify-content:space-between; align-items:center;
            padding:.85rem 0 .9rem; border-bottom:1px solid var(--line); margin-bottom:1rem;
            background:rgba(247,250,252,.98); backdrop-filter:blur(8px); box-shadow:0 1px 0 rgba(215,226,232,.7);}
        .brandbar .name {font-size:1.3rem; line-height:1.25; font-weight:800; color:var(--ink);}
        .brandbar .sub {font-size:.85rem; color:var(--muted);}
        .brandbar .ctx {text-align:right; font-size:.85rem; color:var(--muted);}
        .brandbar .ctx b {color:var(--ink);}
        [data-testid="stWidgetLabel"] p, [data-testid="stCaptionContainer"] p, .stMarkdown p, .stMarkdown li, .stAlert p {
            font-family:"Inter", "Segoe UI", -apple-system, BlinkMacSystemFont, sans-serif !important;
        }
        .request-context {display:flex; justify-content:space-between; align-items:center; gap:1rem; padding:.72rem 1rem; margin:.15rem 0 1rem; border:1px solid var(--line); border-radius:12px; background:linear-gradient(90deg,#F5F9FB,#FFFFFF);}
        .request-context .project {font-weight:750; color:var(--ink); font-size:1rem;}
        .request-context .meta {color:var(--muted); font-size:.8rem; margin-top:.12rem;}
        .request-context .opp {font-weight:700; color:var(--brand); font-size:.82rem; text-align:right;}
        .outlook-grid {display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.65rem; margin:.7rem 0 1.1rem;}
        .outlook-cell {border:1px solid var(--line); border-radius:12px; padding:.7rem .75rem; background:#FFFFFF; min-height:88px; display:flex; flex-direction:column; justify-content:center;}
        .outlook-cell .wk {font-size:.68rem; font-weight:750; color:var(--muted); text-transform:uppercase; letter-spacing:.05em;}
        .outlook-cell .hrs {font-size:1.05rem; font-weight:800; color:var(--ink); margin-top:.18rem;}
        .outlook-cell .state {font-size:.68rem; margin-top:.14rem; color:var(--muted);}
        .outlook-cell.good {border-top:3px solid #00A1DF;}
        .outlook-cell.tight {border-top:3px solid #F5A623; background:#FFF9ED;}
        .outlook-cell.blocked {border-top:3px solid #D64545; background:#FFF3F3;}
        .resource-id {display:inline-block; padding:.2rem .5rem; border-radius:7px; background:#EAF5FA; color:var(--brand); font-size:.72rem; font-weight:750; margin-top:.3rem;}
        .commitment-empty {padding:.8rem .95rem; border:1px dashed var(--line); border-radius:10px; background:#FAFCFD; color:var(--muted);}
        .workflow-tabs {display:flex; gap:.45rem; padding:.15rem 0 .65rem; margin-bottom:.9rem;}
        .workflow-tabs .stButton > button {min-height:2.15rem; border-radius:999px; padding:.25rem .85rem; font-size:.82rem; box-shadow:none;}
        .workflow-tabs .stButton > button[kind="primary"] {box-shadow:0 2px 8px rgba(0,84,135,.14);}
        .match-table {border:1px solid var(--line); border-radius:14px; overflow:hidden; background:#fff; box-shadow:0 2px 10px rgba(37,55,70,.04);}
        .match-row {display:grid; grid-template-columns:.42fr 1.7fr .55fr 1.35fr .72fr .82fr .72fr; align-items:center; column-gap:.7rem; padding:.72rem .85rem; border-top:1px solid #E8EEF2;}
        .match-row.header {border-top:0; background:#F5F9FB; color:#607582; font-size:.7rem; font-weight:750; text-transform:uppercase; letter-spacing:.04em;}
        .match-row.selected {background:#F2F9FC;}
        .match-person {font-weight:750; color:var(--ink);}
        .match-sub {font-size:.72rem; color:var(--muted); margin-top:.1rem;}
        .score-wrap {display:flex; align-items:center; justify-content:flex-start; gap:.35rem;}
        .score-track {height:5px; flex:0 0 58px; min-width:58px; background:#E6EEF2; border-radius:999px; overflow:hidden;}
        .score-fill {height:100%; background:#0077A8; border-radius:999px;}
        .score-value {font-size:.78rem; font-weight:750; color:var(--ink); min-width:32px; text-align:right;}

        .stButton > button {border-radius:10px !important; font-family:"Inter", "Segoe UI", sans-serif !important; font-weight:650 !important; border:1px solid #D3E0E7 !important; transition:all .15s ease !important;}
        .stButton > button:hover {border-color:#8CB8CE !important; box-shadow:0 3px 10px rgba(0,84,135,.10) !important;}
        [data-baseweb="select"] > div, [data-baseweb="input"] > div, [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input {border-radius:10px !important;}
        [data-baseweb="select"] > div {background:#FAFCFD !important; border-color:#D3E0E7 !important;}
        [data-testid="stDateInput"] input {border-radius:10px !important;}
        .stTextArea textarea {border-radius:10px !important;}
        .match-table .stButton > button {font-size:.76rem !important; min-height:2rem !important; border-radius:8px !important;}
        .match-table .stButton {margin:0 !important;}
        .resource-section-heading {margin-top:1.2rem; margin-bottom:.15rem;}
        .detail-section {margin-top:1.75rem;}
        .skill-status {font-size:.7rem;}
        .fit-card {border:1px solid var(--line); border-radius:14px; background:#fff; padding:1.2rem 1.25rem; box-shadow:0 2px 10px rgba(37,55,70,.04); min-height:100%;}
        .fit-card-title {font-size:.95rem; font-weight:800; color:var(--ink);}
        .fit-card-sub {font-size:.72rem; color:var(--muted); margin-top:.18rem; margin-bottom:.75rem;}
        .fit-line {display:grid; grid-template-columns:1fr 2.1fr auto; gap:.65rem; align-items:center; margin:.55rem 0;}
        .fit-label {font-size:.75rem; color:var(--ink); font-weight:650;}
        .fit-track {height:7px; background:#E8EEF2; border-radius:999px; overflow:hidden;}
        .fit-fill {height:100%; background:#0077A8; border-radius:999px;}
        .fit-points {font-size:.72rem; font-weight:750; color:var(--ink); min-width:34px; text-align:right;}
        .alignment-table {border:1px solid var(--line); border-radius:12px; overflow:hidden; background:#fff;}
        .alignment-row {display:grid; grid-template-columns:1.1fr 1fr 1fr .75fr; gap:.6rem; padding:.65rem .8rem; border-top:1px solid #E8EEF2; align-items:center; font-size:.8rem;}
        .alignment-row.header {border-top:0; background:#F5F9FB; font-size:.68rem; color:var(--muted); font-weight:750; text-transform:uppercase; letter-spacing:.04em;}
        .status-pill {display:inline-flex; align-items:center; justify-content:center; width:max-content; padding:.18rem .55rem; border-radius:999px; font-size:.68rem; font-weight:750;}
        .status-pill.meets {background:#EAF9F3; color:#16806A; border:1px solid #B9E8D7;}
        .status-pill.exceeds {background:#EEF5FF; color:#2F67C7; border:1px solid #C9DBF8;}
        .status-pill.missing {background:#FFF3F3; color:#A4442C; border:1px solid #F0C5BC;}
        .detail-grid {display:grid; grid-template-columns:1.08fr .92fr; gap:2.25rem; align-items:stretch; margin-top:1rem;}
        .selected-resource {border:1px solid var(--line); border-radius:14px; background:#fff; padding:.9rem 1rem; margin:.35rem 0 1.15rem; box-shadow:0 2px 10px rgba(37,55,70,.035);}
        .selected-resource .eyebrow {font-size:.66rem; font-weight:800; color:var(--brand); letter-spacing:.09em;}
        .selected-resource .selected-name {font-size:1.05rem; font-weight:800; color:var(--ink); margin-top:.25rem;}
        .section-divider {height:1px; background:var(--line); margin:1.45rem 0;}
        @media (max-width: 900px) {
            .outlook-grid {grid-template-columns:repeat(2,minmax(0,1fr));}
            .match-row {grid-template-columns:.45fr 2fr .6fr 1.2fr .8fr .9fr .8fr; font-size:.76rem;}
            .detail-grid {grid-template-columns:1fr;}
        }
        .pagehead {margin:.2rem 0 1.05rem;}
        .pagehead h1 {font-size:1.5rem; line-height:1.2; margin:0;}
        .pagehead p {margin:.32rem 0 0; color:var(--muted); max-width:78ch;}
        .role-requirement-title {font-size:.98rem; line-height:1.3; font-weight:750; color:var(--ink); margin:1.1rem 0 .2rem;}
        .role-requirement-help {font-size:.78rem; color:var(--muted); margin:0 0 .7rem;}
        .profile-card {border:1px solid var(--line); border-radius:14px; background:#fff; padding:1.15rem 1.2rem; box-shadow:0 2px 10px rgba(37,55,70,.04); min-height:100%;}
        .profile-name {font-size:1.05rem; font-weight:800; color:var(--ink);}
        .profile-meta {font-size:.78rem; color:var(--muted); margin-top:.35rem; line-height:1.5;}
        .profile-contact {font-size:.78rem; color:var(--ink); margin-top:.7rem; line-height:1.55;}
        .section-title-small {font-size:1.02rem; line-height:1.3; font-weight:750; color:var(--ink); margin:.2rem 0 .25rem;}
        .candidate-explorer {display:flex; align-items:center; justify-content:space-between; gap:1.5rem; margin:1.25rem 0 .8rem;}
        .candidate-explorer-title {font-size:1.02rem; line-height:1.3; font-weight:750; color:var(--ink);}
        .candidate-explorer-help {font-size:.72rem; color:var(--muted);}
        [data-testid="stVerticalBlockBorderWrapper"] {border-radius:14px !important; box-shadow:0 2px 12px rgba(37,55,70,.035) !important;}
        .detail-selector {display:flex; justify-content:flex-end; align-items:end; margin:.35rem 0 .75rem;}
        .match-table .stButton > button {font-size:.76rem !important; min-height:2rem !important; border-radius:8px !important;}
        .match-table .stButton {margin:0 !important;}
        .shortlist-empty {padding:.85rem 1rem; border:1px dashed var(--line); border-radius:12px; background:#FAFCFD; color:var(--muted);}
        .fit-overall {display:flex; justify-content:space-between; align-items:flex-end; margin-top:.9rem; padding-top:.75rem; border-top:1px solid #E8EEF2;}
        .fit-overall-label {font-size:1.3rem; font-weight:700; color:var(--muted);}
        .fit-overall-value {font-size:1.5rem; line-height:1; font-weight:850; color:var(--ink); letter-spacing:-.025em;}
        .alignment-row {grid-template-columns:1.15fr .8fr 1fr 1fr .75fr;}
        .alignment-row.header {grid-template-columns:1.15fr .8fr 1fr 1fr .75fr;}
        .resource-id {display:inline-block; padding:.18rem .45rem; border-radius:7px; background:#EAF5FA; color:var(--brand); font-size:.7rem; font-weight:750; margin-top:.3rem;}
        .cardtitle {font-size:.78rem; font-weight:700; letter-spacing:.08em;
            text-transform:uppercase; color:var(--brand); margin:.1rem 0 .55rem;}
        /* Cards in the same row share one height, so field groups stay aligned.
           Element containers keep their natural height, otherwise the card title
           would stretch and push the fields to the bottom of the card. */
        div[data-testid="stColumn"] div:has(.cardtitle):not([data-testid="stElementContainer"])
            {height:100%;}
        div[data-testid="stColumn"] div[data-testid="stElementContainer"]:has(.cardtitle)
            {flex:0 0 auto;}
        div[data-testid="stColumn"] div:has(> div[data-testid="stElementContainer"] .cardtitle)
            {border-radius:10px;}
        .note {padding:.75rem .95rem; border-left:3px solid var(--accent);
            background:var(--soft); border-radius:6px; color:var(--muted); font-size:.9rem;}
        .preview {padding:.65rem .9rem; border:1px dashed var(--line);
            border-radius:8px; color:var(--muted); font-size:.9rem; background:#fff;}
        .pass {color:var(--ok); font-weight:600;}
        .fail {color:var(--risk); font-weight:600;}
        div[data-testid="stMetric"] {border:1px solid var(--line); border-radius:10px;
            padding:.7rem .85rem; background:#fff;}
        div[data-testid="stMetricLabel"] p {color:var(--muted); font-size:.82rem;}
        .stButton > button {border-radius:9px; min-height:2.45rem; font-weight:650; transition:all .15s ease;}
        div[data-baseweb="select"] > div {border-radius:10px !important; border-color:#D7E2E8 !important; background:#FFFFFF !important;}
        div[data-baseweb="select"] > div:focus-within {border-color:#00A1DF !important; box-shadow:0 0 0 2px rgba(0,161,223,.10) !important;}
        div[data-testid="stTextInput"] input, div[data-testid="stNumberInput"] input, div[data-testid="stDateInput"] input {border-radius:9px !important;}
        div[data-testid="stDataEditor"] {border-radius:12px; overflow:hidden;}
        .project-hero {padding:.35rem 0 .9rem; margin-bottom:.5rem;}
        .project-hero .eyebrow {font-size:.72rem; font-weight:700; letter-spacing:.12em;
            text-transform:uppercase; color:var(--accent); margin-bottom:.2rem;}
        .project-hero .title {font-size:2rem; line-height:1.12; font-weight:750; color:var(--ink);}
        .project-hero .meta {margin-top:.35rem; color:var(--muted); font-size:.88rem;}
        .section-label {font-size:.76rem; font-weight:750; letter-spacing:.08em;
            text-transform:uppercase; color:var(--brand); margin:.25rem 0 .45rem;}
        .match-card {border:1px solid var(--line); border-radius:12px; padding:.8rem 1rem;
            background:#fff; box-shadow:0 1px 2px rgba(37,55,70,.04);}
        .match-card .small-label {font-size:.72rem; color:var(--muted); text-transform:uppercase;
            letter-spacing:.07em; font-weight:700;}
        .match-card .value {font-size:1.08rem; color:var(--ink); font-weight:700; margin-top:.12rem;}
        [data-testid="stTabs"] button {font-weight:650;}
        [data-testid="stBaseButton-primary"] {background:#005487; border-color:#005487;}
        [data-testid="stBaseButton-primary"]:hover {background:#003B61; border-color:#003B61;}
        [data-testid="stBaseButton-secondary"]:hover {color:#005487; border-color:#00A1DF; background:#EAF5FA;}
        a {color:#005487;}
        section[data-testid="stFileUploaderDropzone"] {border-radius:10px;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def navigate(page: str) -> None:
    """
    Change page and invalidate match results when returning to input pages.

    Recommendations are only valid for the exact request that produced them.
    """
    if page in {"Project Details", "Team & skills"}:
        st.session_state.results = None
        st.session_state.result_request_fingerprint = None
        st.session_state.selected_for_confirmation = []
        st.session_state.active_match_key = None

    st.session_state.page = page
    st.rerun()


def request_defaults() -> dict:
    return {
        "request_id": "OPP-2026-011",
        "project_name": "Healthcare analytics delivery",
        "start_date": date.today() + timedelta(days=7),
        "end_date": date.today() + timedelta(days=84),
        "allowed_locations": [],
        "time_zones": ["Asia/Kolkata"],
        "geographies": [],
        "languages": ["English"],
        "allowed_teams": [],
        "client": "Axerion Pharma",
        "project_description": "Build patient-level analytics and reporting for delivery teams.",
        "therapeutic_area": "Oncology",
        "kpi_focus_areas": ["Adherence", "Patient Reach", "Service Level"],
        "kpi_focus_area": "Adherence | Patient Reach | Service Level",
        "client_facing": "Y",
        "client_location": "India",
        "client_country": "India",
        "travel_requirement": "No",
        "custom_weights": False,
        "weights": DEFAULT_WEIGHTS.copy(),
        "role_mix": [{
        "designation": "Consultant",
        "grade": 140,
        "headcount": 2,
        "allocation_hours": 21.25,
        "allocation_pct": 50.0,
        "mandatory_skills": {"SQL": 3, "Python": 2},
        "preferred_skills": {"Power BI": 2},
    }],
    }


def init_state() -> None:
    initial = {
        "page": "Project Details",
        "request": request_defaults(),
        "results": None,
        "result_request_fingerprint": None,
        "chat_history": [],
        "editor_version": 0,
        "uploaded_data": None,
        "last_register_result": None,
        "selected_for_confirmation": [],
        "active_match_key": None,

        # ----------------------------------------------------------
        # Optional LLM state
        # ----------------------------------------------------------
        "llm_enabled": False,
        "llm_adapter": None,
        "llm_draft": None,
        "llm_draft_source": "",
        "llm_summary": None,
        "copilot_query": "",
    }

    for key, value in initial.items():
        if key not in st.session_state:
            st.session_state[key] = value


def request_fingerprint(request: dict) -> str:
    """Create a stable identifier for the exact staffing request."""
    payload = json.dumps(
        request,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def get_llm_adapter():
    """
    Return the configured Azure LLM adapter only when AI is enabled.

    No Azure call happens merely because the application is running.
    """
    if not st.session_state.get("llm_enabled", False):
        return None

    adapter = st.session_state.get("llm_adapter")

    if adapter is None:
        adapter = build_azure_llm_adapter()
        st.session_state.llm_adapter = adapter

    if not adapter.configured:
        return None

    return adapter


def governed_llm_values(resources: pd.DataFrame) -> dict:
    """
    Build the controlled vocabulary supplied to the LLM.

    The LLM is not allowed to invent values outside these lists.
    """

    team_options = []

    if resources is not None and "team" in resources.columns:
        team_options = sorted(
            {
                str(value).strip()
                for value in resources["team"].dropna().tolist()
                if str(value).strip()
            }
        )

    return {
        "designations": list(DESIGNATIONS),
        "designation_to_grade": {
            str(key): int(value)
            for key, value in DESIGNATION_TO_GRADE.items()
        },
        "skills": list(SKILL_CATALOG),
        "time_zones": list(TIME_ZONES),
        "geographies": list(GEOGRAPHIES),
        "client_locations": list(CLIENT_LOCATION_TO_COUNTRY.keys()),
        "client_location_to_country": dict(CLIENT_LOCATION_TO_COUNTRY),
        "languages": list(LANGUAGES),
        "teams": team_options,
        "therapeutic_areas": list(THERAPEUTIC_AREAS),
        "kpi_focus_areas": list(KPI_FOCUS_AREAS),
        "travel_requirements": list(TRAVEL_REQUIREMENTS),
        "proficiency_levels": list(PROFICIENCY_LABELS),
        "standard_week_hours": STANDARD_WEEK_HOURS,
    }


def _normalise_llm_list(value) -> list:
    """
    Defensive conversion of an LLM list field.
    """
    if value is None:
        return []

    if isinstance(value, list):
        return [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]

    return [str(value).strip()] if str(value).strip() else []


def _normalise_llm_date(value):
    """
    Convert a valid YYYY-MM-DD style value to a Python date.

    Invalid values become None instead of breaking the application.
    """
    if value in (None, "", "null"):
        return None

    try:
        return pd.Timestamp(value).date()
    except Exception:
        return None


def _governed_skill_level(value):
    """
    Convert a proficiency label or numeric level into the application's
    integer proficiency representation.

    Returns None when the value is not governed.
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        numeric = int(value)
        if 1 <= numeric <= len(PROFICIENCY_LABELS):
            return numeric
        return None

    text = str(value).strip()

    if text in PROFICIENCY_LABELS:
        return PROFICIENCY_LABELS.index(text) + 1

    # Compatibility with possible numeric strings.
    try:
        numeric = int(float(text))
        if 1 <= numeric <= len(PROFICIENCY_LABELS):
            return numeric
    except Exception:
        pass

    return None


def _governed_skills(items) -> dict:
    """
    Convert LLM skill objects into the application's
    {skill: proficiency_level} structure.

    Unknown skills/proficiencies are silently excluded from
    the AI draft rather than entering the deterministic engine.
    """

    if not isinstance(items, list):
        return {}

    result = {}

    for item in items:
        if not isinstance(item, dict):
            continue

        skill = str(item.get("skill") or "").strip()

        if skill not in SKILL_CATALOG:
            continue

        level = _governed_skill_level(
            item.get("proficiency")
        )

        if level is None:
            # No proficiency means the LLM did not provide a
            # sufficiently governed requirement.
            continue

        result[skill] = level

    return result


def normalise_llm_draft(
    draft: dict,
    resources: pd.DataFrame,
) -> dict:
    """
    Validate and normalise an LLM staffing draft before it is
    allowed to influence the deterministic application.

    Work country is intentionally NOT an LLM staffing filter.
    Time zone and geographic expertise are separate governed fields.
    Travel=Yes requires a governed client location/country.
    """

    if not isinstance(draft, dict):
        raise ValueError("The AI draft is not a valid object.")

    team_options = set()
    if resources is not None and "team" in resources.columns:
        team_options = {
            str(value).strip()
            for value in resources["team"].dropna().tolist()
            if str(value).strip()
        }

    time_zones = [
        value for value in _normalise_llm_list(draft.get("time_zones"))
        if value in TIME_ZONES
    ]
    geographies = [
        value for value in _normalise_llm_list(draft.get("geographies"))
        if value in GEOGRAPHIES
    ]
    languages = [
        value for value in _normalise_llm_list(draft.get("languages"))
        if value in LANGUAGES
    ]
    allowed_teams = [
        value for value in _normalise_llm_list(draft.get("allowed_teams"))
        if value in team_options
    ]

    therapeutic_area = draft.get("therapeutic_area")
    if therapeutic_area not in THERAPEUTIC_AREAS:
        therapeutic_area = None

    kpi_focus_areas = [
        value for value in _normalise_llm_list(draft.get("kpi_focus_areas"))
        if value in KPI_FOCUS_AREAS
    ]

    travel_requirement = str(
        draft.get("travel_requirement") or ""
    ).strip()
    if travel_requirement not in TRAVEL_REQUIREMENTS:
        travel_requirement = None

    client_location = str(
        draft.get("client_location") or ""
    ).strip()
    if client_location not in CLIENT_LOCATION_TO_COUNTRY:
        client_location = None

    client_country = CLIENT_LOCATION_TO_COUNTRY.get(client_location)
    raw_client_country = str(
        draft.get("client_country") or ""
    ).strip()
    if client_location and raw_client_country:
        if raw_client_country == CLIENT_LOCATION_TO_COUNTRY[client_location]:
            client_country = raw_client_country
    elif raw_client_country:
        client_country = raw_client_country

    client_facing = draft.get("client_facing")
    if client_facing is not None:
        client_facing = str(client_facing).strip().upper()
        if client_facing not in {"Y", "N"}:
            client_facing = None

    roles = []
    raw_roles = draft.get("roles")

    if isinstance(raw_roles, list):
        for raw_role in raw_roles:
            if not isinstance(raw_role, dict):
                continue

            designation = str(raw_role.get("designation") or "").strip()
            if designation not in DESIGNATIONS:
                continue

            grade = DESIGNATION_TO_GRADE[designation]

            try:
                headcount = int(raw_role.get("headcount"))
            except Exception:
                headcount = None
            if headcount is None or not 1 <= headcount <= 50:
                continue

            try:
                allocation_hours = float(raw_role.get("allocation_hours"))
            except Exception:
                allocation_hours = None
            if (
                allocation_hours is None
                or allocation_hours <= 0
                or allocation_hours > STANDARD_WEEK_HOURS
            ):
                continue

            allocation_pct = allocation_hours / STANDARD_WEEK_HOURS * 100
            mandatory = _governed_skills(raw_role.get("mandatory_skills", []))
            preferred = _governed_skills(raw_role.get("preferred_skills", []))
            preferred = {
                skill: level
                for skill, level in preferred.items()
                if skill not in mandatory
            }

            roles.append(
                {
                    "designation": designation,
                    "grade": grade,
                    "headcount": headcount,
                    "allocation_hours": allocation_hours,
                    "allocation_pct": allocation_pct,
                    "mandatory_skills": mandatory,
                    "preferred_skills": preferred,
                }
            )

    start_date = _normalise_llm_date(draft.get("start_date"))
    end_date = _normalise_llm_date(draft.get("end_date"))

    return {
        "project_name": str(draft.get("project_name") or "").strip() or None,
        "client": str(draft.get("client") or "").strip() or None,
        "project_description": str(
            draft.get("project_description") or ""
        ).strip() or None,
        "start_date": start_date,
        "end_date": end_date,
        "allowed_locations": [],
        "time_zones": time_zones,
        "geographies": geographies,
        "languages": languages,
        "allowed_teams": allowed_teams,
        "therapeutic_area": therapeutic_area,
        "kpi_focus_areas": kpi_focus_areas,
        "client_facing": client_facing,
        "client_location": client_location,
        "client_country": client_country,
        "travel_requirement": travel_requirement,
        "role_mix": roles,
    }


def apply_llm_draft_to_request(
    draft: dict,
) -> None:
    """
    Apply the reviewed AI draft to the normal application request.

    Existing opportunity number and scoring settings are preserved.
    """

    request = st.session_state.request

    updated = request.copy()

    # Never let the LLM invent/replace the opportunity number.
    # The existing Project Details field remains authoritative.
    for field in [
        "project_name",
        "client",
        "project_description",
        "start_date",
        "end_date",
        "time_zones",
        "geographies",
        "languages",
        "allowed_teams",
        "therapeutic_area",
        "kpi_focus_areas",
        "client_location",
        "client_country",
        "travel_requirement",
    ]:
        value = draft.get(field)

        if value is None:
            continue

        if isinstance(value, list) and not value:
            continue

        if value == "":
            continue

        updated[field] = value

    if draft.get("client_facing") in {"Y", "N"}:
        updated["client_facing"] = draft["client_facing"]

    if draft.get("kpi_focus_areas"):
        updated["kpi_focus_area"] = " | ".join(
            draft["kpi_focus_areas"]
        )

    if draft.get("role_mix"):
        updated["role_mix"] = draft["role_mix"]

    # The deterministic engine uses role-specific skills.
    updated["mandatory_skills"] = {}
    updated["preferred_skills"] = {}

    st.session_state.request = updated

    # Force the data editors to rebuild from the new AI draft.
    st.session_state.editor_version += 1

    # Any previous recommendations are now stale.
    st.session_state.results = None
    st.session_state.result_request_fingerprint = None
    st.session_state.llm_summary = None


def llm_draft_display(draft: dict) -> None:
    """
    Human-readable preview of the AI-generated staffing draft.
    """

    st.markdown("### AI-generated draft")

    st.caption(
        "Review this carefully before applying it. "
        "The AI is only preparing the request. "
        "The existing application remains responsible for matching."
    )

    left, right = st.columns(2, gap="large")

    with left:
        st.markdown("**Project**")

        st.write(
            f"**Project:** "
            f"{draft.get('project_name') or 'Not specified'}"
        )

        st.write(
            f"**Client:** "
            f"{draft.get('client') or 'Not specified'}"
        )

        st.write(
            f"**Start:** "
            f"{draft.get('start_date') or 'Not specified'}"
        )

        st.write(
            f"**End:** "
            f"{draft.get('end_date') or 'Not specified'}"
        )

        st.write(
            f"**Time zones:** "
            f"{', '.join(draft.get('time_zones') or []) or 'Not specified'}"
        )

        st.write(
            f"**Geographic expertise:** "
            f"{', '.join(draft.get('geographies') or []) or 'Not specified'}"
        )

        st.write(
            f"**Languages:** "
            f"{', '.join(draft.get('languages') or []) or 'Not specified'}"
        )

    with right:
        st.markdown("**Business context**")

        st.write(
            f"**Therapeutic area:** "
            f"{draft.get('therapeutic_area') or 'Not specified'}"
        )

        st.write(
            f"**KPI focus:** "
            f"{', '.join(draft.get('kpi_focus_areas') or []) or 'Not specified'}"
        )

        st.write(
            f"**Team:** "
            f"{', '.join(draft.get('allowed_teams') or []) or 'All teams'}"
        )

        st.write(
            f"**Travel:** "
            f"{draft.get('travel_requirement') or 'Not specified'}"
        )

        st.write(
            f"**Client location:** "
            f"{draft.get('client_location') or 'Not specified'}"
        )

        st.write(
            f"**Client country:** "
            f"{draft.get('client_country') or 'Not specified'}"
        )

    description = draft.get("project_description")

    if description:
        st.markdown("**Project description**")
        st.info(description)

    st.markdown("### Requested team")

    roles = draft.get("role_mix") or []

    if not roles:
        st.warning(
            "The AI did not identify a complete role requirement. "
            "You can add the role manually in Resource Requirements."
        )
        return

    for role in roles:
        mandatory = role.get("mandatory_skills", {})
        preferred = role.get("preferred_skills", {})

        mandatory_text = (
            ", ".join(
                f"{skill} ({PROFICIENCY_LABELS[level - 1]})"
                for skill, level in mandatory.items()
            )
            or "None"
        )

        preferred_text = (
            ", ".join(
                f"{skill} ({PROFICIENCY_LABELS[level - 1]})"
                for skill, level in preferred.items()
            )
            or "None"
        )

        with st.container(border=True):
            st.markdown(
                f"**{role['headcount']} × "
                f"{role['designation']}**"
            )

            st.write(
                f"Weekly hours/person: "
                f"{role['allocation_hours']:.2f}"
            )

            st.write(
                f"Mandatory: {mandatory_text}"
            )

            st.write(
                f"Nice to have: {preferred_text}"
            )




def _html_block(markup: str) -> None:
    """Render multiline HTML without Markdown interpreting indentation as code."""
    st.markdown(textwrap.dedent(markup).strip(), unsafe_allow_html=True)


def brand_bar() -> None:
    _html_block(
        """
        <div class="brandbar">
            <div>
                <div class="name">CSEC Resource Manager</div>
                <div class="sub">Plan project staffing, check real availability and find capability.</div>
            </div>
            <div class="ctx">IQVIA · Resource allocation workspace</div>
        </div>
        """
    )


def request_context_bar() -> None:
    """Persistent request context for result/tool pages, independent of sidebar state."""
    if st.session_state.page != "Recommendations":
        return
    request = st.session_state.request
    project = request.get("project_name") or "New staffing request"
    opportunity = request.get("request_id") or "Draft"
    client = request.get("client") or "Client not specified"
    start = request.get("start_date")
    end = request.get("end_date")
    window = ""
    if start and end:
        window = f"{pd.Timestamp(start):%d %b %Y} – {pd.Timestamp(end):%d %b %Y}"
    _html_block(
        f"""
        <div class="request-context">
            <div>
                <div class="project">{html.escape(str(project))}</div>
                <div class="meta">{html.escape(str(client))}{(' · ' + html.escape(window)) if window else ''}</div>
            </div>
            <div class="opp">{html.escape(str(opportunity))}</div>
        </div>
        """
    )


def main_navigation() -> None:
    st.markdown('<div class="workflow-tabs">', unsafe_allow_html=True)
    columns = st.columns(len(PAGES), gap="small")
    for column, page in zip(columns, PAGES):
        is_active = st.session_state.page == page
        with column:
            if st.button(
                NAV_LABELS[page],
                key=f"nav_{page}",
                help=NAV_HELP[page],
                width="stretch",
                type="primary" if is_active else "secondary",
            ):
                navigate(page)
    st.markdown('</div>', unsafe_allow_html=True)


def page_header(title: str, description: str) -> None:
    st.markdown(
        f'<div class="pagehead"><h1>{title}</h1><p>{description}</p></div>',
        unsafe_allow_html=True,
    )


def note(text: str) -> None:
    st.markdown(f'<div class="note">{text}</div>', unsafe_allow_html=True)


def card(title: str):
    """Bordered field group; cards in the same row are kept the same height."""
    container = st.container(border=True)
    container.markdown(f'<div class="cardtitle">{title}</div>', unsafe_allow_html=True)
    return container


def _data_source_content(resources: pd.DataFrame, capacity: pd.DataFrame) -> None:
    st.markdown("### Data")
    with st.expander("Data source and quality", expanded=False):
        st.caption(
            f"Active dataset: {len(resources):,} people · "
            f"{len(capacity):,} derived weekly capacity rows."
        )
        st.caption(
            f"Availability is shown as hours from a {STANDARD_WEEK_HOURS:g}-hour PSA week. "
            "Confirmed overlapping allocations in the register are deducted before matching."
        )
        uploaded = st.file_uploader(
            "Upload your own staffing workbook (optional)",
            type=["xlsx", "xls"],
            key="workbook_upload",
            help=(
                "The workbook needs a Resources sheet containing one row per resource."
            ),
        )
        if uploaded is not None and st.button("Load this workbook", key="load_workbook"):
            try:
                raw_resources = load_workbook(uploaded)
                if raw_resources is None:
                    st.error("A Resources sheet is required.")
                else:
                    st.session_state.uploaded_data = canonicalize_resources(raw_resources)
                    st.session_state.results = None
                    st.success("Resource workbook loaded. Run the match again to use it.")
                    st.session_state.results = None
                    st.success("Workbook loaded. Run the match again to use it.")
            except Exception:
                st.error("That file could not be read. Please check the sheet names and columns.")
        if st.session_state.uploaded_data is not None and st.button(
            "Switch back to sample data", key="reset_workbook"
        ):
            st.session_state.uploaded_data = None
            st.session_state.results = None
            st.rerun()
        health = dataset_health(resources)
        problems = health["resources_errors"]
        if problems:
            for problem in problems[:5]:
                st.error(problem)
        else:
            st.success("All data quality checks passed.")
    with st.expander("Upload schema", expanded=False):
        st.caption("Workbook sheet: Resources (one row per person)")
        st.code(
            "resource_id, resource_name, team, grade, role_title, location, "
            "work_city, time_zone, languages, skills, domains, development_interests, "
            "years_experience, delivery_rating, profile_updated",
            language=None,
        )
        st.caption("Skills use Skill:Level separated by pipes. Example:")
        st.code("SQL:3|Python:2|Power BI:3", language=None)
        
        st.caption("Grade codes: 130 Analyst/Associate Consultant, 140 Consultant, then +10.")
    with st.expander("Allocation register schema", expanded=False):
        st.caption("Output workbook: staffing_register.xlsx")
        st.caption("Opportunities sheet")
        st.code(", ".join(OPPORTUNITY_COLUMNS), language=None)
        st.caption("Allocations sheet")
        st.code(", ".join(ALLOCATION_COLUMNS), language=None)
        try:
            opportunities, allocations = load_register(REGISTER_PATH, resources)
            st.caption(
                f"Stored history: {len(opportunities)} opportunities · "
                f"{len(allocations)} confirmed allocations"
            )
        except Exception:
            st.caption("The register will be created when the app can write to the data folder.")


def data_source_panel(resources: pd.DataFrame, capacity: pd.DataFrame) -> None:
    with st.sidebar:
        _data_source_content(resources, capacity)


def rows_from_skills(skills: dict) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Skill": skill, "Proficiency": PROFICIENCY_LABELS[int(level) - 1]}
            for skill, level in skills.items()
        ],
        columns=["Skill", "Proficiency"],
    )


def skills_from_rows(rows: pd.DataFrame) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for _, row in rows.dropna(how="all").iterrows():
        skill = str(row.get("Skill", "")).strip()
        proficiency = str(row.get("Proficiency", "")).strip()
        if skill in SKILL_CATALOG and proficiency in PROFICIENCY:
            parsed[skill] = PROFICIENCY[proficiency]
    return parsed


def role_rows(request: dict) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Designation": row["designation"],
                "People required": int(row["headcount"]),
                "Weekly hours/person": float(
                    row.get("allocation_hours", 21.25)
                ),
            }
            for row in request.get("role_mix", [])
        ],
        columns=[
            "Designation",
            "People required",
            "Weekly hours/person",
        ],
    )


def roles_from_rows(rows: pd.DataFrame) -> list[dict]:
    roles = []

    for _, row in rows.dropna(how="all").iterrows():
        designation = str(row.get("Designation", "")).strip()

        if designation not in DESIGNATION_TO_GRADE:
            continue

        headcount = pd.to_numeric(
            row.get("People required"),
            errors="coerce",
        )

        allocation_hours = pd.to_numeric(
            row.get("Weekly hours/person"),
            errors="coerce",
        )

        if pd.isna(allocation_hours):
            allocation_hours = 21.25

        allocation_pct = (
            float(allocation_hours)
            / STANDARD_WEEK_HOURS
            * 100
        )

        roles.append(
            {
                "designation": designation,
                "grade": DESIGNATION_TO_GRADE[designation],
                "headcount": int(headcount)
                if pd.notna(headcount)
                else 0,
                "allocation_hours": float(allocation_hours),
                "allocation_pct": float(allocation_pct),
            }
        )

    return roles


def shortlist_columns() -> dict:
    return {
        "rank": st.column_config.NumberColumn("#", help="Rank within this role."),
        "resource_name": st.column_config.TextColumn("Person"),
        "resource_id": st.column_config.TextColumn("Employee ID"),
        "role_title": st.column_config.TextColumn("Designation"),
        "grade": st.column_config.NumberColumn("Grade"),
        "team": st.column_config.TextColumn("Team"),
        "location": st.column_config.TextColumn("Country"),
        "work_city": st.column_config.TextColumn("Work city"),
        "time_zone": st.column_config.TextColumn("Time zone"),
        "total_score": st.column_config.ProgressColumn(
            "Fit score", min_value=0, max_value=100, format="%.1f"
        ),
        "minimum_available_hours": st.column_config.NumberColumn(
            "Lowest weekly free hours",
            min_value=0,
            max_value=STANDARD_WEEK_HOURS,
            format="%.2f h",
            help="Free hours in the person's tightest week after confirmed allocations.",
        ),
    }


def render_project_brief(resources: pd.DataFrame, capacity: pd.DataFrame) -> None:
    page_header(
        "Staffing Request",
        "Define the engagement context, delivery period, allocation needs, and staffing constraints.",
    )
    request = st.session_state.request
    st.caption(r"\* required")

    engagement_column, window_column = st.columns(2, gap="large")
    with engagement_column:
        with card("Engagement Details"):
            request_id = st.text_input(
                "Opportunity ID *",
                value=request.get("request_id", ""),
                placeholder="OPP-2026-011",
                help="Used as the Opportunity Number in the register.",
            )
            existing_opportunity_numbers = set()

            try:
                opportunities, _ = load_register(REGISTER_PATH, resources)

                if not opportunities.empty:
                    existing_opportunity_numbers = set(
                        opportunities["Opportunity Number"]
                        .astype(str)
                        .str.strip()
                        .str.casefold()
                    )
            except Exception:
                existing_opportunity_numbers = set()

            request_id_normalized = request_id.strip().casefold()

            if (
                request_id_normalized
                and request_id_normalized in existing_opportunity_numbers
            ):
                # st.error(
                #     f"Opportunity number `{request_id.strip()}` already exists "
                #     "in the staffing register. Please enter a new opportunity number."
                # )
                opportunity_number_exists = True
            else:
                opportunity_number_exists = False

            
            project_name = st.text_input(
                "Engagement Name *",
                value=request.get("project_name", ""),
                placeholder="India omnichannel analytics rollout",
                help="The delivery name shown in recommendations and the allocation register.",
            )
            client = st.text_input(
                "Client *",
                value=request.get("client", ""),
                placeholder="Axerion Pharma",
                help="The client attached to this opportunity in the register.",
            )
            therapeutic_area = st.selectbox(
                "Therapeutic area *",
                THERAPEUTIC_AREAS,
                index=(
                    THERAPEUTIC_AREAS.index(request["therapeutic_area"])
                    if request.get("therapeutic_area") in THERAPEUTIC_AREAS
                    else 0
                ),
                help="Used for portfolio reporting; it does not affect candidate scoring.",
            )
    with window_column:
        with card("Delivery Requirements"):
            start_column, end_column = st.columns(2)
            with start_column:
                start_date = st.date_input(
                    "Start date *",
                    value=request.get("start_date"),
                    help="Weekly availability is checked from this date.",
                )
            with end_column:
                end_date = st.date_input(
                    "End date *",
                    value=request.get("end_date"),
                    help="The final week for which this allocation needs capacity.",
                )
            
            client_facing = st.radio(
                "Client-Facing Role",
                ["Yes", "No"],
                index=0 if request.get("client_facing", "Y") in ("Y", "Yes") else 1,
                horizontal=True,
                help="Identifies whether the allocated people will work directly with the client.",
            )

    eligibility_column, record_column = st.columns(2, gap="large")
    with eligibility_column:
        with card("Staffing Constraints"):
            zones = st.multiselect(
                "Time zone",
                TIME_ZONES,
                default=[
                    x for x in request.get("time_zones", [])
                    if x in TIME_ZONES
                ],
                placeholder="Any time zone",
                help=(
                    "If selected, a person must work in one of these time zones. "
                    "This is independent of work country."
                ),
            )
            geographies = st.multiselect(
                "Geographic expertise",
                GEOGRAPHIES,
                default=[
                    x for x in request.get("geographies", [])
                    if x in GEOGRAPHIES
                ],
                placeholder="Any geography",
                help=(
                    "Knowledge of a market or geography. This does not mean "
                    "the person physically works there."
                ),
            )
            languages = st.multiselect(
                "Language",
                LANGUAGES,
                default=[
                    x for x in request.get("languages", [])
                    if x in LANGUAGES
                ],
                placeholder="Any language",
                help="A person must speak every language selected.",
            )
            team_options = sorted(resources.team.dropna().astype(str).unique())
            specific_teams = st.multiselect(
                "Preferred Delivery Team",
                team_options,
                default=[
                    x for x in request.get("allowed_teams", [])
                    if x in team_options
                ],
                placeholder="All teams",
                help="An exact eligibility filter. Team is never scored.",
            )
    with record_column:
        with card("Project Context"):
            kpi_focus_areas = st.multiselect(
                "Business Outcome Areas *",
                KPI_FOCUS_AREAS,
                default=[
                    x for x in request.get("kpi_focus_areas", [])
                    if x in KPI_FOCUS_AREAS
                ],
                placeholder="Choose the KPIs this work moves",
                help=(
                    "The business measures this opportunity is expected to improve."
                ),
            )
            location_column, travel_column = st.columns(2)
            client_location_options = list(CLIENT_LOCATION_TO_COUNTRY.keys())
            current_client_location = request.get("client_location")
            client_location_index = (
                client_location_options.index(current_client_location)
                if current_client_location in client_location_options
                else 0
            )
            with location_column:
                client_location = st.selectbox(
                    "Client location",
                    client_location_options,
                    index=client_location_index,
                    help=(
                        "Governed client city/location from the staffing register. "
                        "The selected value determines the client country."
                    ),
                )
            with travel_column:
                travel_options = ["No", "Yes"]
                current_travel = request.get("travel_requirement", "No")
                travel_index = (
                    travel_options.index(current_travel)
                    if current_travel in travel_options
                    else 0
                )
                travel_requirement = st.selectbox(
                    "Travel requirement",
                    travel_options,
                    index=travel_index,
                    help=(
                        "No = work country does not constrain matching. "
                        "Yes = the person's work country must match the client country."
                    ),
                )

            client_country = CLIENT_LOCATION_TO_COUNTRY.get(
                client_location,
                "",
            )

            st.caption(
                f"Client country derived from location: **{client_country or 'Not available'}**"
            )

            project_description = st.text_area(
                "Scope and Responsibilities",
                value=request.get("project_description", ""),
                height=122,
                placeholder="What the team will build or analyse.",
                help="A concise delivery summary written to the opportunity register.",
            )

    note(
        "Location, team, time zone, language, designation, mandatory skills, and minimum availability "
        "are treated as eligibility constraints. Resources who do not meet these requirements "
        "will not be recommended."
    )

    problems = []
    if opportunity_number_exists:
        problems.append(
            "Opportunity number already exists in the staffing register. Please enter an unique opportunity number."
        )
    if not request_id.strip():
        problems.append("Opportunity number is required.")
    if not project_name.strip():
        problems.append("Project name is required.")
    if not client.strip():
        problems.append("Client is required.")
    if travel_requirement == "Yes" and not client_country:
        problems.append("Client country is required when travel is Yes.")
    if not kpi_focus_areas:
        problems.append("At least one KPI focus area is required.")
    if end_date < start_date:
        problems.append("The end date is before the start date.")
    if (end_date - start_date).days > 730:
        problems.append("A request cannot be longer than two years.")
    for problem in problems:
        st.warning(problem)

    if st.button(
        "Save and Continue to Requirements",
        type="primary",
        disabled=bool(problems),
    ):
        st.session_state.request = request | {
            "request_id": request_id.strip(),
            "project_name": project_name.strip(),
            "start_date": start_date,
            "end_date": end_date,
            "allowed_locations": [],
            "allowed_teams": specific_teams,
            "time_zones": zones,
            "geographies": geographies,
            "languages": languages,
            "client": client.strip(),
            "project_description": project_description.strip() or project_name.strip(),
            "therapeutic_area": therapeutic_area,
            "kpi_focus_areas": kpi_focus_areas,
            "kpi_focus_area": " | ".join(kpi_focus_areas),
            "client_facing": ("Y" if client_facing == "Yes" else "N"),
            "client_location": client_location,
            "client_country": client_country,
            "travel_requirement": travel_requirement,
        }
        navigate("Team & skills")


def render_team_and_skills(resources: pd.DataFrame, capacity: pd.DataFrame) -> None:
    page_header(
        "Resource Requirements",
        "Define the required roles, headcount, capabilities, proficiency levels, and recommendation criteria.",
    )
    request = st.session_state.request
    version = st.session_state.editor_version

    st.markdown('<div class="section-title-small">Role and Headcount Requirements *</div>', unsafe_allow_html=True)
    st.caption("Add each role required for the staffing request and specify the corresponding headcount.")
    edited_roles = st.data_editor(
        role_rows(request),
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        key=f"role_editor_{version}",
        column_config={
            "Designation": st.column_config.SelectboxColumn(
                "Role / Designation",
                options=DESIGNATIONS,
                required=True,
                help="Grade is set automatically: 130 Analyst and Associate Consultant, 140 Consultant, then +10 per level.",
            ),
            "People required": st.column_config.NumberColumn(
                "Required Headcount",
                min_value=1,
                max_value=50,
                step=1,
                required=True,
                help="How many people you need at this designation.",
            ),
            "Weekly hours/person": st.column_config.NumberColumn(
                "Required Weekly Allocation per Resource",
                min_value=0.25,
                max_value=STANDARD_WEEK_HOURS,
                step=0.25,
                format="%.2f",
                required=True,
                help=(
                    f"Weekly demand for each person in this role. "
                    f"A full week is {STANDARD_WEEK_HOURS:g} hours."
                ),
            ),
        },
    )
    parsed_roles = roles_from_rows(edited_roles)
    if parsed_roles:
        st.markdown(
            '<div class="preview">Staffing Requirement: '
            + " · ".join(
                f"{row['headcount']} {row['designation']}{'' if row['headcount'] == 1 else 's'}, Grade {row['grade']}"
                for row in parsed_roles
            )
            + "</div>",
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown('<div class="section-title-small">Capability Requirements by Role</div>', unsafe_allow_html=True)
    st.caption("Specify the required and preferred capabilities for each role. Required capabilities determine eligibility, while preferred capabilities influence recommendation ranking.")
    existing_roles = {
        row["designation"]: row for row in request.get("role_mix", [])
    }
    role_skill_rows = {}
    for role in parsed_roles:
        designation = role["designation"]
        existing = existing_roles.get(designation, {})
        mandatory_default = existing.get(
            "mandatory_skills", request.get("mandatory_skills", {})
        )
        preferred_default = existing.get(
            "preferred_skills", request.get("preferred_skills", {})
        )
        st.markdown(
            f'<div class="role-requirement-title">{html.escape(str(designation))} · Grade {role["grade"]} · {role["headcount"]} needed</div>',
            unsafe_allow_html=True,
        )
        mandatory_column, preferred_column = st.columns(2, gap="large")
        with mandatory_column:
            st.markdown("**Required Capabilities**")
            mandatory_rows = st.data_editor(
                rows_from_skills(mandatory_default),
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
                key=f"mandatory_{designation}_{version}",
                column_config={
                    "Skill": st.column_config.SelectboxColumn(
                        "Skill", options=SKILL_CATALOG, required=True,
                        help="A capability every eligible person must have.",
                    ),
                    "Proficiency": st.column_config.SelectboxColumn(
                        "Minimum Proficiency", options=PROFICIENCY_LABELS, required=True,
                        help="Minimum governed proficiency; candidates below it are excluded.",
                    ),
                },
            )
        with preferred_column:
            st.markdown("**Preferred Capabilities**")
            preferred_rows = st.data_editor(
                rows_from_skills(preferred_default),
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
                key=f"preferred_{designation}_{version}",
                column_config={
                    "Skill": st.column_config.SelectboxColumn(
                        "Skill", options=SKILL_CATALOG, required=True,
                        help="A capability that improves ranking but is not mandatory.",
                    ),
                    "Proficiency": st.column_config.SelectboxColumn(
                        "Target Proficiency", options=PROFICIENCY_LABELS, required=True,
                        help="Preferred proficiency used when ranking eligible people.",
                    ),
                },
            )
        role_skill_rows[designation] = (mandatory_rows, preferred_rows)

    st.divider()
    with st.expander("Recommendation Weighting", expanded=False):
        st.caption(
            "Adjust the relative importance of capability alignment, proficiency depth, and capacity fit when ranking eligible resources."
        )
        weight_labels = {
            "mandatory_skills": "Mandatory skills (%)",
            "preferred_skills": "Nice-to-have skills (%)",
            "proficiency": "Proficiency depth (%)",
            "capacity": "Capacity fit (%)",
        }
        custom_weights = st.checkbox(
            "Customize Recommendation Weights",
            value=bool(request.get("custom_weights", False)),
            help="Weights only order people who already passed every requirement.",
        )
        stored_weights = request.get("weights", DEFAULT_WEIGHTS)
        if custom_weights:
            weight_columns = st.columns(4)
            entered_weights = {}
            for column, (key, label) in zip(weight_columns, weight_labels.items()):
                with column:
                    entered_weights[key] = st.number_input(
                        label,
                        min_value=0,
                        max_value=100,
                        value=int(round(stored_weights.get(key, DEFAULT_WEIGHTS[key]) * 100)),
                        step=5,
                        key=f"weight_{key}",
                        help="Share of the 100-point fit score assigned to this component.",
                    )
            weight_total = sum(entered_weights.values())
            selected_weights = {key: value / 100 for key, value in entered_weights.items()}
            gap = weight_total - 100
            if gap > 0:
                st.error(f"Weights total {weight_total}%. Remove {gap}% to reach exactly 100%.")
            elif gap < 0:
                st.error(f"Weights total {weight_total}%. Add {abs(gap)}% to reach exactly 100%.")
            else:
                st.success("Weights total 100%.")
        else:
            selected_weights = DEFAULT_WEIGHTS.copy()
            weight_total = 100
            st.caption(
                "Default scoring: "
                + " · ".join(
                    f"{weight_labels[key].removesuffix(' (%)')} {value:.0%}"
                    for key, value in DEFAULT_WEIGHTS.items()
                )
            )

    st.divider()
    back_column, run_column = st.columns([1, 2])
    with back_column:
        if st.button("Back to Staffing Request", width="stretch"):
            navigate("Project Details")
    with run_column:
        if st.button(
            "Generate Candidate Recommendations",
            type="primary",
            width="stretch",
            disabled=weight_total != 100,
        ):
            completed_roles = []
            overlaps = []
            for role in parsed_roles:
                mandatory_rows, preferred_rows = role_skill_rows[role["designation"]]
                mandatory = skills_from_rows(mandatory_rows)
                preferred = skills_from_rows(preferred_rows)
                overlap = set(mandatory).intersection(preferred)
                overlaps.extend(f"{role['designation']}: {skill}" for skill in overlap)
                completed_roles.append(
                    role
                    | {
                        "mandatory_skills": mandatory,
                        "preferred_skills": {
                            skill: level
                            for skill, level in preferred.items()
                            if skill not in overlap
                        },
                    }
                )
            candidate_request = request | {
                "role_mix": completed_roles,
                # Empty request-level skills ensure the engine uses each role's
                # own requirements rather than a shared fallback.
                "mandatory_skills": {},
                "preferred_skills": {},
                "custom_weights": custom_weights,
                "weights": selected_weights,
            }
            report = validate_request(candidate_request)
            health = dataset_health(resources)
            errors = health["resources_errors"] + report.errors
            if weight_total != 100:
                errors.append("Scoring weights must total 100%.")
            
            if errors:
                st.error("Please fix the following before matching:")
                for problem in errors[:8]:
                    st.write(f"- {problem}")
            else:
                if overlaps:
                    st.info(
                        "These duplicate skills stay mandatory: "
                        + ", ".join(overlaps)
                    )
                with st.status(
                    "Finding matching people...",
                    expanded=True,
                ) as status:
                    st.write("Running the matching engine...")
                    st.write(
                        f"Assessing {len(resources):,} people across "
                        f"{len(candidate_request.get('role_mix', []))} requested roles."
                    )

                    match_result = run_matching(
                        resources,
                        capacity,
                        candidate_request,
                        selected_weights,
                    )

                    st.write("Preparing recommendations...")

                    status.update(
                        label="Matching completed",
                        state="complete",
                        expanded=False,
                    )

                st.session_state.request = candidate_request
                st.session_state.results = match_result
                st.session_state.result_request_fingerprint = request_fingerprint(
                    candidate_request
                )
                st.session_state.selected_for_confirmation = []
                st.session_state.active_match_key = None

                st.session_state.page = "Recommendations"
                st.rerun()

def _group_capacity_runs(capacity_chart: pd.DataFrame, required_hours: float) -> list[dict]:
    """Collapse consecutive project weeks with the same availability state."""
    runs = []
    if capacity_chart.empty:
        return runs

    frame = capacity_chart.reset_index(drop=True).copy()
    for idx, row in frame.iterrows():
        free = round(float(row["Available hours"]), 1)
        if free + 1e-9 < required_hours:
            state = "Below request"
            css = "blocked"
        elif free < required_hours + 4.25:
            state = "Tight"
            css = "tight"
        else:
            state = "Available"
            css = "good"

        if runs:
            prev = runs[-1]
            same = (
                prev["state"] == state
                and abs(prev["hours"] - free) < 0.05
            )
        else:
            same = False

        if same:
            prev["end"] = idx + 1
        else:
            runs.append(
                {
                    "start": idx + 1,
                    "end": idx + 1,
                    "hours": free,
                    "state": state,
                    "css": css,
                }
            )

    return runs


def _skill_status(required_level: int, actual_level: int | None) -> tuple[str, str]:
    if actual_level is None:
        return "Missing", "missing"
    if actual_level > required_level:
        return "Exceeds", "exceeds"
    return "Meets", "meets"


def _fit_composition_html(score_components: dict, weights: dict | None = None) -> str:
    """Render each deterministic score contribution against its own maximum.

    The engine stores weighted points, not raw component percentages. For example,
    a capacity contribution of 20.0 under a 20% capacity weight is a full 100%
    of the capacity component. The bar therefore uses the configured weight as
    the component maximum rather than comparing every bar with the largest
    component.
    """
    ordered = [
        ("mandatory_skills", "Mandatory skills"),
        ("preferred_skills", "Preferred skills"),
        ("proficiency", "Proficiency"),
        ("capacity", "Capacity"),
    ]
    effective_weights = dict(DEFAULT_WEIGHTS)
    if weights:
        for key, raw in weights.items():
            try:
                effective_weights[key] = float(raw)
            except (TypeError, ValueError):
                pass

    items = []
    for key, label in ordered:
        if key in score_components:
            try:
                value = float(score_components[key])
            except (TypeError, ValueError):
                continue
            maximum = max(effective_weights.get(key, 0.0) * 100.0, 0.0001)
            items.append((label, value, maximum))

    known = {key for key, _ in ordered}
    for key, raw in score_components.items():
        if key in known:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        # Unknown deterministic components have no configured weight, so use
        # their observed value only as a safe fallback rather than inventing a
        # business rule.
        maximum = max(abs(value), 1.0)
        items.append((str(key).replace("_", " ").title(), value, maximum))

    rows = []
    for label, value, maximum in items:
        width = max(0.0, min(100.0, value / maximum * 100.0))
        rows.append(
            textwrap.dedent(
                f"""
                <div class="fit-line">
                    <div class="fit-label">{html.escape(label)}</div>
                    <div class="fit-track"><div class="fit-fill" style="width:{width:.1f}%"></div></div>
                    <div class="fit-points">{value:.1f}</div>
                </div>
                """
            ).strip()
        )
    return "".join(rows)



def render_recommendations(
    resources: pd.DataFrame,
    capacity: pd.DataFrame,
    confirmed_allocations: pd.DataFrame | None = None,
) -> None:
    page_header(
        "Resource Matches",
        "Review eligible resources ranked by capability alignment, availability, and overall staffing fit.",
    )
    result = st.session_state.results
    request = st.session_state.request

    current_fingerprint = request_fingerprint(request)
    stored_fingerprint = st.session_state.get("result_request_fingerprint")

    if result is None or stored_fingerprint != current_fingerprint:
        st.info(
            "No current candidate match is available for the current requirements. "
            "Return to Resource Requirements and generate candidate recommendations."
        )
        if st.button("Go to Resource Requirements", type="primary"):
            navigate("Team & skills")
        return

    diagnostics = result.diagnostics
    metrics = st.columns(4)
    metrics[0].metric("Roles requested", diagnostics.get("requested_slots", 0))
    metrics[1].metric("Roles fillable", diagnostics.get("fillable_slots", 0))
    metrics[2].metric("Resources evaluated", diagnostics.get("resources_assessed", 0))
    metrics[3].metric("Planning Horizon", diagnostics.get("request_window_weeks", 0))

    st.caption(
        "Every candidate shown here has passed the mandatory designation, capability, "
        "time-zone, language, travel, and weekly-availability eligibility gates. "
        "Match Score only ranks eligible candidates."
    )

    roles = diagnostics.get("roles", [])
    if not roles:
        st.warning("No valid role was requested. Add a role in Resource Requirements.")
        return

    st.caption(
        "Role coverage: "
        + " | ".join(
            f"{role['designation']}: {role['eligible']} candidates for {role['requested']} requested"
            for role in roles
        )
    )

    eligible = result.table[result.table.status.eq("Eligible")].copy()

    if eligible.empty:
        st.error("No candidate meets every mandatory requirement across the requested roles.")
        st.caption(
            "Nothing was relaxed automatically. Review the requirements if additional "
            "candidates are needed."
        )
        near_matches = build_near_matches(result.table)
        if near_matches:
            near_frame = pd.DataFrame(near_matches)
            near_frame["minimum_available_hours"] = (
                near_frame["minimum_available_pct"] / 100 * STANDARD_WEEK_HOURS
            )
            near_frame["exclusion_reasons"] = near_frame.exclusion_reasons.map(", ".join)
            st.dataframe(
                near_frame[
                    [
                        "resource_name",
                        "role_title",
                        "location",
                        "minimum_available_hours",
                        "exclusion_reasons",
                    ]
                ],
                hide_index=True,
                width="stretch",
                column_config={
                    "resource_name": "Candidate",
                    "role_title": "Role",
                    "location": "Country",
                    "minimum_available_hours": st.column_config.NumberColumn(
                        "Minimum Weekly Availability", format="%.2f h"
                    ),
                    "exclusion_reasons": "Eligibility issue",
                },
            )
        if st.button("Back to Resource Requirements", type="primary"):
            navigate("Team & skills")
        return

    eligible = eligible.sort_values(
        ["requested_designation", "rank", "resource_name"]
    ).copy()
    eligible["minimum_available_hours"] = (
        eligible["minimum_available_pct"] / 100 * STANDARD_WEEK_HOURS
    )
    eligible["candidate_key"] = (
        eligible.role_key.astype(str) + "|" + eligible.resource_id.astype(str)
    )

    valid_keys = set(eligible.candidate_key)
    st.session_state.selected_for_confirmation = [
        key for key in st.session_state.get("selected_for_confirmation", [])
        if key in valid_keys
    ]
    selected_keys = list(st.session_state.get("selected_for_confirmation", []))

    # ---------------------------------------------------------------
    # Candidate Ranking
    # ---------------------------------------------------------------
    st.markdown("#### Candidate Ranking")
    st.caption("Use Shortlist only when a candidate should be included in the final staffing decision.")

    with st.container(border=True):
        header_cols = st.columns(
            [0.42, 1.75, 0.55, 1.35, 0.72, 0.82, 0.72],
            gap="small",
        )
        headers = [
            "Rank",
            "Candidate",
            "Grade",
            "Team",
            "Match Score",
            "Minimum Weekly Availability",
            "Shortlist",
        ]
        for col, header in zip(header_cols, headers):
            with col:
                st.markdown(
                    f"<div style='font-size:.64rem;font-weight:800;color:#607582;text-transform:uppercase;letter-spacing:.045em;padding:.15rem 0 .5rem'>{html.escape(header)}</div>",
                    unsafe_allow_html=True,
                )

        for _, row in eligible.iterrows():
            key = row.candidate_key
            shortlisted = key in st.session_state.selected_for_confirmation
            row_cols = st.columns(
                [0.42, 1.75, 0.55, 1.35, 0.72, 0.82, 0.72],
                gap="small",
            )

            with row_cols[0]:
                rank_value = row["rank"] if "rank" in row.index else None
                rank_text = (
                    str(int(rank_value))
                    if pd.notna(rank_value)
                    else ""
                )
                st.markdown(
                    f"<div style='padding:.65rem 0;font-size:.77rem;font-weight:750;color:#253746'>{rank_text}</div>",
                    unsafe_allow_html=True,
                )

            with row_cols[1]:
                st.markdown(
                    f"<div class='match-person' style='padding:.18rem 0 0'>{html.escape(str(row.resource_name))}</div>"
                    f"<div class='match-sub'>{html.escape(str(row.resource_id))} · {html.escape(str(row.requested_designation))}</div>",
                    unsafe_allow_html=True,
                )

            with row_cols[2]:
                st.markdown(
                    f"<div style='padding:.65rem 0;font-size:.77rem;color:#253746'>{html.escape(str(row.grade))}</div>",
                    unsafe_allow_html=True,
                )

            with row_cols[3]:
                st.markdown(
                    f"<div style='padding:.65rem 0;font-size:.75rem;color:#253746;line-height:1.25'>{html.escape(str(row.team))}</div>",
                    unsafe_allow_html=True,
                )

            with row_cols[4]:
                st.markdown(
                    f"<div style='padding:.65rem 0;font-size:.86rem;font-weight:800;color:#005487'>{float(row.total_score):.1f}</div>",
                    unsafe_allow_html=True,
                )

            with row_cols[5]:
                st.markdown(
                    f"<div style='padding:.65rem 0;font-size:.75rem;color:#253746'>{float(row.minimum_available_hours):.1f} h</div>",
                    unsafe_allow_html=True,
                )

            with row_cols[6]:
                if st.button(
                    "Shortlisted" if shortlisted else "Shortlist",
                    key=f"toggle_shortlist_{key}",
                    width="stretch",
                    type="primary" if shortlisted else "secondary",
                ):
                    current = list(st.session_state.selected_for_confirmation)
                    if key in current:
                        current.remove(key)
                    else:
                        current.append(key)
                    st.session_state.selected_for_confirmation = current
                    st.rerun()

            st.markdown(
                "<div style='height:1px;background:#E8EEF2;margin:.02rem 0'></div>",
                unsafe_allow_html=True,
            )

    # ---------------------------------------------------------------
    # Optional AI explanation, advisory only
    # ---------------------------------------------------------------
    if st.session_state.get("llm_enabled", False):
        st.divider()
        st.markdown("### Recommendation Rationale")
        st.caption(
            "This explanation is generated from the deterministic candidate ranking above. "
            "AI does not re-rank, exclude, or change candidates."
        )
        adapter = get_llm_adapter()
        if adapter is None:
            st.info(
                "AI explanation is unavailable because the approved Azure OpenAI configuration is not active."
            )
        else:
            if st.button("Generate AI explanation", key="generate_ai_recommendation_summary"):
                summary_rows = []
                for _, row in eligible.head(5).iterrows():
                    summary_rows.append(
                        {
                            "rank": int(row["rank"]) if pd.notna(row.get("rank")) else None,
                            "requested_designation": row.get("requested_designation"),
                            "resource_name": row.get("resource_name"),
                            "grade": row.get("grade"),
                            "team": row.get("team"),
                            "location": row.get("location"),
                            "time_zone": row.get("time_zone"),
                            "total_score": row.get("total_score"),
                            "minimum_available_hours": row.get("minimum_available_hours"),
                        }
                    )

                request_summary = {
                    "project_name": request.get("project_name"),
                    "client": request.get("client"),
                    "start_date": request.get("start_date"),
                    "end_date": request.get("end_date"),
                    "time_zones": request.get("time_zones"),
                    "geographies": request.get("geographies"),
                    "client_location": request.get("client_location"),
                    "client_country": request.get("client_country"),
                    "travel_requirement": request.get("travel_requirement"),
                    "languages": request.get("languages"),
                    "role_mix": request.get("role_mix"),
                }

                with st.spinner("Preparing AI explanation..."):
                    try:
                        st.session_state.llm_summary = adapter.summarize_recommendations(
                            request_summary, summary_rows
                        )
                    except Exception as exc:
                        st.error("The AI summary could not be generated.")
                        st.exception(exc)

            if st.session_state.get("llm_summary"):
                st.info(st.session_state.llm_summary)

    # ---------------------------------------------------------------
    # Candidate Profile explorer
    # ---------------------------------------------------------------
    # Every eligible candidate can be inspected here. Shortlisting remains a
    # separate decision made only from Candidate Ranking above.
    option_keys = eligible.candidate_key.tolist()
    label_map = {
        row.candidate_key: f"{row.resource_name} · {row.requested_designation} · {row.team}"
        for _, row in eligible.iterrows()
    }
    current_key = (
        st.session_state.get("active_match_key")
        if st.session_state.get("active_match_key") in option_keys
        else option_keys[0]
    )

    st.markdown(
        '<div class="section-divider"></div>', unsafe_allow_html=True
    )
    explorer_left, explorer_right = st.columns([1.0, 1.15], gap="large")
    with explorer_left:
        st.markdown('<div class="candidate-explorer-title">Candidate Profile</div>', unsafe_allow_html=True)
    with explorer_right:
        selected_profile_key = st.selectbox(
            "Candidate",
            option_keys,
            index=option_keys.index(current_key),
            format_func=lambda key: label_map.get(key, str(key)),
            key="candidate_profile_selector",
            help="Browse any eligible candidate. Shortlist candidates only when you are ready to include them in the staffing decision.",
        )
        st.session_state.active_match_key = selected_profile_key

    active_key = st.session_state.get("active_match_key") or selected_profile_key
    person = eligible[eligible.candidate_key.eq(active_key)].iloc[0]

    # ---------------------------------------------------------------
    # Candidate Profile
    # ---------------------------------------------------------------
    profile_column, fit_column = st.columns([1.03, 0.97], gap="large")

    with profile_column:
        with st.container(border=True):
            st.markdown(f"**{html.escape(str(person.resource_name))}**", unsafe_allow_html=True)
            role_line = (
                f"{html.escape(str(person.role_title))} · "
                f"Grade {html.escape(str(person.grade))} · "
                f"{html.escape(str(person.team))}"
            )
            location_line = (
                f"{html.escape(str(person.location))}"
                f"{(' · ' + html.escape(str(person.work_city))) if 'work_city' in person.index and person.work_city else ''}"
                f" · {html.escape(str(person.time_zone))}"
            )
            st.markdown(role_line, unsafe_allow_html=True)
            st.markdown(location_line, unsafe_allow_html=True)
            st.markdown(
                f"**Email:** {html.escape(str(person.contact_email or 'Not provided'))}",
                unsafe_allow_html=True,
            )
            manager_line = f"**Manager:** {html.escape(str(person.manager_name))}"
            if person.manager_email:
                manager_line += f" ({html.escape(str(person.manager_email))})"
            st.markdown(manager_line, unsafe_allow_html=True)

    with fit_column:
        with st.container(border=True):
            st.markdown("**Match Score Composition**")
            st.caption("Weighted contribution to the deterministic match score.")
            score_components = person.score_components or {}
            ordered = [
                ("mandatory_skills", "Mandatory skills"),
                ("preferred_skills", "Preferred skills"),
                ("proficiency", "Proficiency"),
                ("capacity", "Capacity"),
            ]
            score_weights = request.get("weights", DEFAULT_WEIGHTS) or DEFAULT_WEIGHTS
            items = []
            for comp_key, label in ordered:
                if comp_key in score_components:
                    try:
                        value = float(score_components[comp_key])
                    except (TypeError, ValueError):
                        continue
                    maximum = max(float(score_weights.get(comp_key, DEFAULT_WEIGHTS.get(comp_key, 0.0))) * 100.0, 0.0001)
                    items.append((label, value, maximum))
            for label, value, maximum in items:
                width = max(0.0, min(100.0, value / maximum * 100.0))
                st.markdown(
                    f"<div class='fit-line'><div class='fit-label'>{html.escape(label)}</div>"
                    f"<div class='fit-track'><div class='fit-fill' style='width:{width:.1f}%'></div></div>"
                    f"<div class='fit-points'>{value:.1f}</div></div>",
                    unsafe_allow_html=True,
                )
            st.markdown(
                f"<div class='fit-overall'><span class='fit-overall-label'>Overall Match Score</span>"
                f"<span class='fit-overall-value'>{float(person.total_score):.1f} / 100</span></div>",
                unsafe_allow_html=True,
            )

    # ---------------------------------------------------------------
    # Capability Alignment
    # ---------------------------------------------------------------
    source_rows = resources[
        resources.resource_id.astype(str).eq(str(person.resource_id))
    ]
    source = source_rows.iloc[0] if not source_rows.empty else None
    candidate_skills = parse_skill_string(source.skills) if source is not None else {}

    mandatory_for_role = person.get(
        "requested_mandatory_skills", request.get("mandatory_skills", {})
    )
    preferred_for_role = person.get(
        "requested_preferred_skills", request.get("preferred_skills", {})
    )
    combined = []
    for skill, level in mandatory_for_role.items():
        combined.append((skill, level, "Required"))
    for skill, level in preferred_for_role.items():
        if skill not in mandatory_for_role:
            combined.append((skill, level, "Preferred"))

    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
    st.markdown("#### Capability Alignment")
    if combined:
        rows_html = [
            "<div class='alignment-row header'><div>Capability</div><div>Requirement</div>"
            "<div>Requested Proficiency</div><div>Resource Proficiency</div><div>Alignment</div></div>"
        ]
        for skill, level, requirement_type in combined:
            actual = candidate_skills.get(skill)
            status, css = _skill_status(level, actual)
            requested_label = (
                PROFICIENCY_LABELS[level - 1]
                if 1 <= level <= len(PROFICIENCY_LABELS)
                else "Not specified"
            )
            actual_label = (
                PROFICIENCY_LABELS[actual - 1]
                if actual is not None and 1 <= actual <= len(PROFICIENCY_LABELS)
                else "Not listed"
            )
            rows_html.append(
                f"<div class='alignment-row'><div><b>{html.escape(str(skill))}</b></div>"
                f"<div>{requirement_type}</div><div>{html.escape(requested_label)}</div>"
                f"<div>{html.escape(actual_label)}</div>"
                f"<div><span class='status-pill {css}'>{status}</span></div></div>"
            )
        _html_block(
            "<div class='alignment-table'>" + "".join(rows_html) + "</div>"
        )
    else:
        st.markdown(
            '<div class="commitment-empty">No capabilities were requested, so ranking used available capacity only.</div>',
            unsafe_allow_html=True,
        )

    # ---------------------------------------------------------------
    # Capacity assessment for selected candidate
    # ---------------------------------------------------------------
    resource_capacity = capacity[
        capacity.resource_id.astype(str).eq(str(person.resource_id))
    ].copy()

    if not resource_capacity.empty:
        resource_capacity["week_start"] = pd.to_datetime(
            resource_capacity["week_start"], errors="coerce"
        ).dt.normalize()

        start_week = pd.Timestamp(request["start_date"]).normalize()
        start_week = start_week - pd.Timedelta(days=int(start_week.weekday()))
        end_week = pd.Timestamp(request["end_date"]).normalize()
        end_week = end_week - pd.Timedelta(days=int(end_week.weekday()))

        resource_capacity = resource_capacity[
            resource_capacity.week_start.between(start_week, end_week)
        ].sort_values("week_start")

        if not resource_capacity.empty:
            required_hours = float(person.get("requested_allocation_hours", 0) or 0)
            if required_hours <= 0:
                matching_role = next(
                    (
                        row for row in request.get("role_mix", [])
                        if str(row.get("designation"))
                        == str(person.get("requested_designation"))
                    ),
                    None,
                )
                required_hours = float(
                    matching_role.get("allocation_hours", 0)
                    if matching_role else 0
                )

            capacity_chart = resource_capacity[
                ["week_start", "available_capacity_pct", "active_project_count"]
            ].copy()
            capacity_chart["Available hours"] = (
                capacity_chart["available_capacity_pct"] / 100 * STANDARD_WEEK_HOURS
            )
            capacity_chart["Required allocation"] = required_hours
            capacity_chart["Concurrent projects"] = (
                capacity_chart["active_project_count"].fillna(0).astype(int)
            )
            capacity_chart = capacity_chart.reset_index(drop=True)
            capacity_chart["Project week"] = [
                f"W{i + 1}" for i in range(len(capacity_chart))
            ]

            st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
            st.markdown("#### Capacity Assessment")
            st.caption(
                f"{len(capacity_chart)} project weeks · available hours already include confirmed staffing-register commitments."
            )

            runs = _group_capacity_runs(capacity_chart, required_hours)
            cells = []
            for run in runs:
                week_label = (
                    f"W{run['start']}"
                    if run["start"] == run["end"]
                    else f"W{run['start']}–W{run['end']}"
                )
                cells.append(
                    f"<div class='outlook-cell {run['css']}'><div class='wk'>{week_label}</div>"
                    f"<div class='hrs'>{run['hours']:.1f}h / week</div><div class='state'>{run['state']}</div></div>"
                )
            _html_block("<div class='outlook-grid'>" + "".join(cells) + "</div>")

            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=capacity_chart["Project week"],
                    y=capacity_chart["Available hours"],
                    name="Available hours",
                    marker_color="#0077A8",
                    hovertemplate="%{x}<br>Available: %{y:.1f} h<extra></extra>",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=capacity_chart["Project week"],
                    y=capacity_chart["Required allocation"],
                    name="Required allocation",
                    mode="lines+markers",
                    line=dict(color="#E34A33", dash="dash", width=2),
                    marker=dict(size=5),
                    hovertemplate="%{x}<br>Required: %{y:.1f} h<extra></extra>",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=capacity_chart["Project week"],
                    y=capacity_chart["Concurrent projects"],
                    name="Concurrent projects",
                    mode="lines",
                    line=dict(color="#7B4DFF", width=2),
                    yaxis="y2",
                    hovertemplate="%{x}<br>Projects: %{y}<extra></extra>",
                )
            )
            max_projects = max(1, int(capacity_chart["Concurrent projects"].max()))
            fig.update_layout(
                height=310,
                margin=dict(l=8, r=8, t=8, b=8),
                plot_bgcolor="white",
                paper_bgcolor="white",
                bargap=0.25,
                xaxis=dict(
                    title="Project week",
                    showgrid=False,
                    categoryorder="array",
                    categoryarray=capacity_chart["Project week"].tolist(),
                    tickmode="linear",
                    dtick=max(1, len(capacity_chart) // 8),
                ),
                yaxis=dict(
                    title="Hours",
                    rangemode="tozero",
                    range=[
                        0,
                        max(
                            STANDARD_WEEK_HOURS,
                            float(capacity_chart["Available hours"].max()) * 1.12,
                        ),
                    ],
                    gridcolor="#E3EAF0",
                ),
                yaxis2=dict(
                    title="Projects",
                    overlaying="y",
                    side="right",
                    rangemode="tozero",
                    range=[0, max_projects + 0.5],
                    dtick=1,
                    showgrid=False,
                ),
                legend=dict(
                    orientation="h",
                    yanchor="top",
                    y=-0.18,
                    xanchor="left",
                    x=0,
                ),
                hoverlabel=dict(bgcolor="white"),
            )
            st.plotly_chart(
                fig,
                width="stretch",
                config={"displayModeBar": False, "responsive": True},
            )

            peak_projects = int(capacity_chart["Concurrent projects"].max())
            min_free = float(capacity_chart["Available hours"].min())
            st.caption(
                f"Peak concurrent projects: {peak_projects} · minimum weekly availability: {min_free:.1f} h"
            )

            if confirmed_allocations is not None and not confirmed_allocations.empty:
                commitments = confirmed_allocations.copy()
                commitments["Employee ID"] = commitments["Employee ID"].astype(str).str.strip()
                commitments = commitments[
                    commitments["Employee ID"].eq(str(person.resource_id))
                ].copy()
                if "Status" in commitments.columns:
                    commitments = commitments[
                        commitments["Status"].fillna("").astype(str).str.casefold().eq("confirmed")
                    ]
                if not commitments.empty:
                    commitments["Allocation Start Date"] = pd.to_datetime(
                        commitments["Allocation Start Date"], errors="coerce"
                    )
                    commitments["Allocation End Date"] = pd.to_datetime(
                        commitments["Allocation End Date"], errors="coerce"
                    )
                    commitments = commitments[
                        commitments["Allocation Start Date"].notna()
                        & commitments["Allocation End Date"].notna()
                    ]
                    heat_rows = []
                    for _, alloc in commitments.iterrows():
                        values = []
                        for week in capacity_chart["week_start"]:
                            week_end = week + pd.Timedelta(days=4)
                            overlap = (
                                alloc["Allocation Start Date"].normalize() <= week_end
                                and alloc["Allocation End Date"].normalize() >= week
                            )
                            values.append(
                                float(alloc["Allocation Hours / Week"])
                                if overlap else 0.0
                            )
                        heat_rows.append(
                            {
                                "Project": str(alloc["Project Name"]),
                                **{
                                    f"W{i + 1}": value
                                    for i, value in enumerate(values)
                                },
                            }
                        )
                    heat = pd.DataFrame(heat_rows).drop_duplicates(subset=["Project"])
                    if not heat.empty:
                        st.markdown("##### Current Commitments")
                        heat = heat.set_index("Project")
                        fig_heat = px.imshow(
                            heat,
                            text_auto=True,
                            aspect="auto",
                            labels={
                                "x": "Project week",
                                "y": "Project",
                                "color": "Hours",
                            },
                            color_continuous_scale=[
                                "#F4F8FA",
                                "#B8DCF0",
                                "#0077A8",
                            ],
                        )
                        fig_heat.update_layout(
                            height=max(180, min(360, 55 * len(heat) + 80)),
                            margin=dict(l=0, r=0, t=5, b=0),
                            coloraxis_colorbar=dict(title="h/week"),
                        )
                        st.plotly_chart(
                            fig_heat,
                            width="stretch",
                            config={"displayModeBar": False},
                        )

    # ---------------------------------------------------------------
    # Confirm staffing decision
    # ---------------------------------------------------------------
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
    st.markdown("#### Confirm Staffing Decision")
    st.caption(
        "Confirm the shortlisted resources. Current capacity is rechecked before the register is updated."
    )

    if selected_keys:
        selected_rows = eligible[
            eligible.candidate_key.isin(selected_keys)
        ].copy()
        chip_html = []
        for _, row in selected_rows.iterrows():
            chip_html.append(
                f"<span style='display:inline-flex;align-items:center;padding:.3rem .6rem;"
                f"margin:0 .35rem .35rem 0;border-radius:999px;background:#EAF5FA;"
                f"color:#005487;font-size:.74rem;font-weight:700'>"
                f"{html.escape(str(row.resource_name))} · "
                f"{html.escape(str(row.requested_designation))}</span>"
            )
        st.markdown("".join(chip_html), unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="shortlist-empty">No resources have been shortlisted.</div>',
            unsafe_allow_html=True,
        )

    _, confirm_column = st.columns([2.2, 1], gap="large")
    with confirm_column:
        confirm_clicked = st.button(
            "Confirm Selected Resources",
            type="primary",
            width="stretch",
            disabled=not selected_keys,
        )

    if confirm_clicked:
        selected = eligible[eligible.candidate_key.isin(selected_keys)]
        if selected.empty:
            st.warning("Shortlist at least one candidate.")
        else:
            fresh_result = run_matching(
                resources,
                capacity,
                request,
                request.get("weights", DEFAULT_WEIGHTS),
            )
            fresh_eligible = fresh_result.table[
                fresh_result.table.status.eq("Eligible")
            ].copy()
            fresh_eligible["candidate_key"] = (
                fresh_eligible.role_key.astype(str)
                + "|"
                + fresh_eligible.resource_id.astype(str)
            )
            approved_keys = set(fresh_eligible.candidate_key)
            blocked = selected[~selected.candidate_key.isin(approved_keys)]
            selected = selected[selected.candidate_key.isin(approved_keys)]

            if not blocked.empty:
                st.warning(
                    f"{len(blocked)} shortlisted resource(s) no longer have enough "
                    "weekly availability after confirmed allocations and were not allocated."
                )
            if selected.empty:
                st.error("None of the shortlisted resources still meet the current weekly-capacity gate.")
                return

            try:
                register_result = append_confirmed_allocations(
                    REGISTER_PATH, resources, request, selected
                )
                st.session_state.last_register_result = register_result
                st.session_state.selected_for_confirmation = []
                st.session_state.active_match_key = None
                st.success(
                    f"Saved {register_result['allocations_added']} allocation row(s) to "
                    f"{REGISTER_PATH.name}."
                )
                if register_result["allocations_skipped"]:
                    st.info(
                        f"{register_result['allocations_skipped']} row(s) already existed and were not duplicated."
                    )
            except PermissionError:
                st.error(
                    "The register is open in Excel. Close the workbook, then confirm again."
                )
            except Exception:
                st.error("The allocation register could not be updated safely.")

    if st.session_state.last_register_result:
        _, allocations = load_register(REGISTER_PATH, resources)
        opportunity_number = st.session_state.last_register_result["opportunity_number"]
        st.markdown("##### Confirmed rows for this opportunity")
        st.dataframe(
            allocations[
                allocations["Opportunity Number"].astype(str).eq(opportunity_number)
            ][ALLOCATION_COLUMNS],
            hide_index=True,
            width="stretch",
        )


def horizon_availability(capacity: pd.DataFrame, from_date, weeks: int):
    """Return per-person availability statistics for the selected future horizon."""
    frame = capacity.copy()
    frame["week_start"] = pd.to_datetime(
        frame["week_start"], errors="coerce"
    ).dt.normalize()
    first = pd.Timestamp(from_date).normalize()
    first = first - pd.Timedelta(days=first.weekday())
    last = first + pd.Timedelta(weeks=weeks - 1)
    window = frame[frame["week_start"].between(first, last)]
    if window.empty:
        return pd.DataFrame(), []

    grid = window.pivot_table(
        index=window["resource_id"].astype(str),
        columns="week_start",
        values="available_capacity_pct",
        aggfunc="min",
    )
    week_columns = sorted(grid.columns)
    second_half = week_columns[len(week_columns) // 2:]
    stats = pd.DataFrame(
        {
            "sustained_pct": grid.min(axis=1),
            "typical_pct": grid.median(axis=1),
            "weeks_present": grid.count(axis=1),
            "first_week_pct": grid[week_columns[0]],
            "later_pct": grid[second_half].min(axis=1),
        }
    )
    incomplete = stats.weeks_present.lt(len(week_columns))
    stats.loc[incomplete, ["sustained_pct", "later_pct"]] = 0.0
    return stats, week_columns


def top_skills(raw: str, limit: int = 4) -> str:
    """Return the strongest named capabilities for capacity portfolio views."""
    parsed = parse_skill_string(raw)
    ranked = sorted(parsed.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return ", ".join(skill for skill, _ in ranked)

def skill_holders(
    resources: pd.DataFrame,
    minimum_level: int,
) -> dict[str, list[str]]:
    """Return resource IDs for people meeting the minimum skill proficiency."""
    holders: dict[str, list[str]] = {}

    for row in resources.itertuples(index=False):
        for skill, level in parse_skill_string(row.skills).items():
            if level >= minimum_level:
                holders.setdefault(skill, []).append(
                    str(row.resource_id)
                )

    return holders


def render_bench_view(pool: pd.DataFrame, threshold_hours: float) -> None:
    threshold_pct = threshold_hours / STANDARD_WEEK_HOURS * 100
    available_now = pool[pool.sustained_pct.ge(threshold_pct)]
    frees_later = pool[
        pool.sustained_pct.lt(threshold_pct) & pool.later_pct.ge(threshold_pct)
    ]

    metrics = st.columns(4)
    metrics[0].metric("Free all horizon", len(available_now))
    metrics[1].metric("Freeing up later", len(frees_later))
    metrics[2].metric(
        "Unused weekly hours",
        f"{available_now.sustained_pct.sum() / 100 * STANDARD_WEEK_HOURS:,.1f} h",
        help="Sum of each person's lowest weekly free hours across the horizon.",
    )
    metrics[3].metric("Teams holding it", int(available_now.team.nunique()))

    if available_now.empty and frees_later.empty:
        st.info(
            f"Nobody holds {threshold_hours:g} free hours in every week of this horizon. "
            "Lower the threshold or move the start week."
        )
        return

    if not available_now.empty:
        by_team = (
            available_now.groupby("team", as_index=False)
            .agg(
                Weekly_hours=(
                    "sustained_pct",
                    lambda values: values.sum() / 100 * STANDARD_WEEK_HOURS,
                )
            )
            .sort_values("Weekly_hours", ascending=True)
            .tail(12)
        )
        figure = px.bar(by_team, x="Weekly_hours", y="team", orientation="h")
        figure.update_layout(
            height=max(260, 28 * len(by_team)),
            margin=dict(l=0, r=10, t=10, b=0),
            yaxis_title="",
            xaxis_title="Unused hours per week",
        )
        st.plotly_chart(figure, width="stretch")

    bench = pd.concat([available_now, frees_later])
    bench = bench.assign(
        readiness=bench.sustained_pct.ge(threshold_pct).map(
            {True: "Free all horizon", False: "Frees up later"}
        ),
        sustained_hours=bench.sustained_pct / 100 * STANDARD_WEEK_HOURS,
        later_hours=bench.later_pct / 100 * STANDARD_WEEK_HOURS,
        capabilities=bench.skills.map(top_skills),
    ).sort_values(["readiness", "sustained_pct"], ascending=[True, False])
    st.dataframe(
        bench[
            [
                "readiness",
                "resource_name",
                "role_title",
                "team",
                "location",
                "sustained_hours",
                "later_hours",
                "capabilities",
                "manager_name",
                "contact_email",
            ]
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "readiness": "Readiness",
            "resource_name": "Person",
            "role_title": "Designation",
            "team": "Team",
            "location": "Country",
            "sustained_hours": st.column_config.NumberColumn(
                "Free every week", format="%.2f h"
            ),
            "later_hours": st.column_config.NumberColumn(
                "Free in later weeks", format="%.2f h"
            ),
            "capabilities": "Strongest skills",
            "manager_name": "Manager",
            "contact_email": "Email",
        },
    )


def render_coverage_risk_view(pool: pd.DataFrame, threshold_hours: float) -> None:
    threshold_pct = threshold_hours / STANDARD_WEEK_HOURS * 100
    minimum_level = PROFICIENCY["Proficient"]
    holders = skill_holders(pool, minimum_level)
    indexed = pool.set_index(pool.resource_id.astype(str))
    rows = []
    for skill in SKILL_CATALOG:
        ids = holders.get(skill, [])
        people = indexed.loc[[i for i in ids if i in indexed.index]] if ids else indexed.iloc[0:0]
        deployable = people[people.sustained_pct.ge(threshold_pct)]
        concentration = (
            people.team.value_counts(normalize=True).max() if not people.empty else 0.0
        )
        if people.empty:
            risk = "No coverage"
        elif deployable.empty:
            risk = "Fully committed"
        elif len(people) <= 2:
            risk = "Single point of failure"
        elif len(people) <= 5 or concentration >= 0.6 or people.location.nunique() == 1:
            risk = "Concentrated"
        else:
            risk = "Healthy"
        rows.append(
            {
                "skill": skill,
                "risk": risk,
                "proficient": len(people),
                "deployable": len(deployable),
                "teams": int(people.team.nunique()),
                "countries": int(people.location.nunique()),
                "concentration": float(concentration),
            }
        )
    frame = pd.DataFrame(rows)
    severity = {
        "No coverage": 0,
        "Single point of failure": 1,
        "Fully committed": 2,
        "Concentrated": 3,
        "Healthy": 4,
    }

    metrics = st.columns(4)
    metrics[0].metric("Skills with no cover", int(frame.risk.eq("No coverage").sum()))
    metrics[1].metric(
        "Single points of failure", int(frame.risk.eq("Single point of failure").sum())
    )
    metrics[2].metric("Nobody free", int(frame.risk.eq("Fully committed").sum()))
    metrics[3].metric("Healthy skills", int(frame.risk.eq("Healthy").sum()))

    only_risk = st.toggle("Show only skills at risk", value=True)
    visible = frame[frame.risk.ne("Healthy")] if only_risk else frame
    visible = visible.assign(order=visible.risk.map(severity)).sort_values(
        ["order", "deployable", "proficient", "skill"]
    )
    if visible.empty:
        st.success("Every skill in the catalogue has healthy, deployable coverage.")
        return

    thinnest = visible.head(12).sort_values("deployable", ascending=True)
    figure = px.bar(thinnest, x="deployable", y="skill", orientation="h")
    figure.update_layout(
        height=max(260, 28 * len(thinnest)),
        margin=dict(l=0, r=10, t=10, b=0),
        yaxis_title="",
        xaxis_title="People proficient and free in this horizon",
    )
    st.plotly_chart(figure, width="stretch")

    st.dataframe(
        visible.drop(columns="order"),
        hide_index=True,
        width="stretch",
        column_config={
            "skill": "Skill",
            "risk": "Risk",
            "proficient": st.column_config.NumberColumn("Proficient or above"),
            "deployable": st.column_config.NumberColumn("Of those, free"),
            "teams": st.column_config.NumberColumn("Teams"),
            "countries": st.column_config.NumberColumn("Countries"),
            "concentration": st.column_config.ProgressColumn(
                "Largest team share", min_value=0, max_value=1, format="%.0f%%"
            ),
        },
    )


def render_capacity_trend_view(
    pool: pd.DataFrame,
    capacity: pd.DataFrame,
    from_date,
    weeks: int,
    threshold_hours: float,
) -> None:
    threshold_pct = threshold_hours / STANDARD_WEEK_HOURS * 100
    frame = capacity.copy()
    frame["week_start"] = pd.to_datetime(frame["week_start"], errors="coerce").dt.normalize()
    frame["resource_id"] = frame.resource_id.astype(str)
    frame = frame[frame.resource_id.isin(set(pool.resource_id.astype(str)))]
    first = pd.Timestamp(from_date).normalize()
    first = first - pd.Timedelta(days=first.weekday())
    window = frame[frame.week_start.between(first, first + pd.Timedelta(weeks=weeks - 1))]
    if window.empty:
        st.info("No derived capacity weeks are available for this horizon.")
        return

    weekly = (
        window.groupby("week_start", as_index=False)
        .agg(
            free_hours=(
                "available_capacity_pct",
                lambda values: values.sum() / 100 * STANDARD_WEEK_HOURS,
            ),
            median_hours=(
                "available_capacity_pct",
                lambda values: values.median() / 100 * STANDARD_WEEK_HOURS,
            ),
            people_free=(
                "available_capacity_pct",
                lambda values: int((values >= threshold_pct).sum()),
            ),
        )
        .sort_values("week_start")
    )

    metrics = st.columns(3)
    metrics[0].metric("Free hours now", f"{weekly.iloc[0].free_hours:,.1f} h/week")
    metrics[1].metric(
        "Free hours at horizon end", f"{weekly.iloc[-1].free_hours:,.1f} h/week"
    )
    metrics[2].metric(
        "Tightest week",
        f"{weekly.loc[weekly.free_hours.idxmin()].week_start:%d %b}",
    )

    figure = px.line(weekly, x="week_start", y="free_hours", markers=True)
    figure.update_layout(
        height=320,
        margin=dict(l=0, r=10, t=10, b=0),
        xaxis_title="Week beginning",
        yaxis_title="Free hours per week",
    )
    # Anchor at zero so a stable trend does not look like a spike.
    figure.update_yaxes(rangemode="tozero")
    st.plotly_chart(figure, width="stretch")

    st.dataframe(
        weekly,
        hide_index=True,
        width="stretch",
        column_config={
            "week_start": st.column_config.DateColumn("Week beginning", format="DD MMM YYYY"),
            "free_hours": st.column_config.NumberColumn(
                "Free hours per week", format="%.1f h"
            ),
            "median_hours": st.column_config.NumberColumn(
                "Median free hours", format="%.2f h"
            ),
            "people_free": st.column_config.NumberColumn(
                f"People at {threshold_hours:g} hours or more"
            ),
        },
    )


def render_capacity_and_risk(resources: pd.DataFrame, capacity: pd.DataFrame) -> None:
    page_header(
        "Capacity Assessment",
        "Review availability, existing commitments, allocation feasibility, and staffing risks.",
    )

    controls = st.columns([1, 1, 1, 1.4], gap="medium")
    with controls[0]:
        from_date = st.date_input(
            "From week",
            value=date.today() + timedelta(days=7),
            help="The analysis starts on the Monday containing this date.",
        )
    with controls[1]:
        weeks = st.slider(
            "Horizon",
            min_value=4,
            max_value=12,
            value=8,
            help="How many future capacity weeks to assess.",
        )
    with controls[2]:
        threshold_hours = st.number_input(
            "Minimum weekly free hours",
            min_value=0.25,
            max_value=STANDARD_WEEK_HOURS,
            value=21.25,
            step=0.25,
            format="%.2f",
            help=(
                f"The hours someone must have free to count as deployable. "
                f"A full PSA week is {STANDARD_WEEK_HOURS:g} hours."
            ),
        )
    with controls[3]:
        team_options = sorted(resources.team.dropna().astype(str).unique())
        teams = st.multiselect(
            "Team",
            team_options,
            placeholder="All teams",
            help="Limit portfolio capacity and skill risk to selected organisational teams.",
        )

    stats, week_columns = horizon_availability(capacity, from_date, weeks)
    if stats.empty:
        st.info("No derived capacity weeks are available for this horizon. Move the start week.")
        return

    pool = resources.copy()
    if teams:
        pool = pool[pool.team.isin(teams)]
    pool = (
        pool.assign(_key=pool.resource_id.astype(str))
        .join(stats, on="_key")
        .drop(columns="_key")
    )
    for column in ["sustained_pct", "typical_pct", "later_pct", "first_week_pct"]:
        pool[column] = pd.to_numeric(pool[column], errors="coerce").fillna(0.0)
    if pool.empty:
        st.info("No people match this team filter.")
        return

    st.caption(
        f"{len(week_columns)} weeks from {week_columns[0]:%d %b %Y} to "
        f"{week_columns[-1]:%d %b %Y} · {len(pool):,} people · "
        "availability is derived from confirmed staffing commitments."
    )

    views = ["Bench and redeployment", "Capability coverage risk", "Capacity trend"]
    view = st.radio(
        "View",
        views,
        horizontal=True,
        label_visibility="collapsed",
        help=(
            "Bench identifies usable time, coverage risk identifies fragile skills, "
            "and trend shows total free hours week by week."
        ),
    )
    st.write("")
    if view == views[0]:
        render_bench_view(pool, threshold_hours)
    elif view == views[1]:
        render_coverage_risk_view(pool, threshold_hours)
    else:
        render_capacity_trend_view(
            pool, capacity, from_date, weeks, threshold_hours
        )


def describe_filters(intent) -> list[str]:
    chips = []
    if intent.skills:
        chips.append("Skills: " + ", ".join(sorted(intent.skills)))
    if intent.designations:
        chips.append("Designation: " + ", ".join(sorted(intent.designations)))
    if intent.locations:
        chips.append("Country: " + ", ".join(sorted(intent.locations)))
    if intent.geographies:
        chips.append("Geography: " + ", ".join(sorted(intent.geographies)))
    if intent.domains:
        chips.append("Domain: " + ", ".join(sorted(intent.domains)))
    if intent.time_zones:
        chips.append("Time zone: " + ", ".join(sorted(intent.time_zones)))
    if intent.languages:
        chips.append("Language: " + ", ".join(sorted(intent.languages)))
    if intent.availability_min is not None:
        minimum_hours = intent.availability_min / 100 * STANDARD_WEEK_HOURS
        maximum_hours = (
            intent.availability_max / 100 * STANDARD_WEEK_HOURS
            if intent.availability_max is not None
            else None
        )
        band = (
            f"{minimum_hours:.2f} hours/week or more"
            if maximum_hours is None
            else f"{minimum_hours:.2f} to {maximum_hours:.2f} hours/week"
        )
        chips.append("Availability: " + band)
    if intent.start_date:
        chips.append(f"From: {intent.start_date:%d %b %Y}")
    return chips



def render_copilot(
    resources: pd.DataFrame,
    capacity: pd.DataFrame,
) -> None:
    page_header(
        "Ask Copilot",
        "Provides AI-assisted explanations, alternatives, and reviewable staffing actions without changing deterministic matching.",
    )

    # ---------------------------------------------------------------
    # AI master switch
    # ---------------------------------------------------------------

    use_llm = st.checkbox(
        "Use AI capabilities",
        value=st.session_state.get("llm_enabled", False),
        help=(
            "When enabled, Azure OpenAI may interpret natural-language "
            "requests and prepare an editable staffing draft. "
            "When disabled, the existing deterministic application "
            "continues to work normally."
        ),
    )

    st.session_state.llm_enabled = use_llm

    if not use_llm:
        st.info(
            "AI is currently OFF. The existing deterministic Copilot "
            "search remains available below."
        )

        # -----------------------------------------------------------
        # Existing deterministic search
        # -----------------------------------------------------------

        examples = [
            "Consultants with SQL and Python who works in Germany",
            "GenAI experts in India time zone",
            "Power BI people in India with 21-25 hours free from 2026-09-21",
        ]

        example_columns = st.columns(len(examples))

        for index, example in enumerate(examples):
            if example_columns[index].button(
                example,
                key=f"deterministic_example_{index}",
                width="stretch",
                help="Use this example question.",
            ):
                st.session_state.copilot_query = example

        query = st.text_input(
            "What are you looking for?",
            value=st.session_state.get(
                "copilot_query",
                "",
            ),
            placeholder=(
                "For example: Tableau consultants in India "
                "with 21 hours free from 2026-09-21"
            ),
            help=(
                "Mention skills, geography expertise, designation, "
                "time zone, weekly free hours and a start date."
            ),
        )

        if st.button(
            "Search",
            type="primary",
            key="deterministic_search",
        ):
            if not query.strip():
                st.warning(
                    "Type a question first, or choose one of the examples above."
                )
            else:
                intent, found = discovery_search(
                    resources,
                    capacity,
                    query,
                    limit=25,
                    llm_adapter=None,
                )

                st.session_state.chat_history.insert(
                    0,
                    {
                        "query": query,
                        "intent": intent,
                        "rows": found,
                    },
                )

        for item in st.session_state.chat_history[:3]:
            with st.container(border=True):
                st.markdown(
                    f"**You asked:** {item['query']}"
                )

                chips = describe_filters(
                    item["intent"]
                )

                if chips:
                    st.caption(
                        "Understood as — "
                        + " | ".join(chips)
                    )

                found = item["rows"]

                if found.empty:
                    st.info(
                        "Nobody matched every part of that question. "
                        "Try removing one condition, or check the spelling "
                        "of the skill or country."
                    )
                    continue

                found = found.copy()

                if "minimum_available_pct" in found:
                    found["minimum_available_hours"] = (
                        found["minimum_available_pct"]
                        / 100
                        * STANDARD_WEEK_HOURS
                    )

                st.caption(
                    f"{len(found)} people found."
                )

                st.dataframe(
                    found[
                        [
                            column
                            for column in [
                                "rank",
                                "resource_name",
                                "role_title",
                                "grade",
                                "team",
                                "location",
                                "minimum_available_hours",
                                "key_skills",
                                "contact_email",
                                "manager_name",
                            ]
                            if column in found.columns
                        ]
                    ],
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "rank": "#",
                        "resource_name": "Person",
                        "role_title": "Designation",
                        "grade": "Grade",
                        "team": "Team",
                        "location": "Country",
                        "minimum_available_hours":
                            st.column_config.NumberColumn(
                                "Free weekly hours",
                                format="%.2f h",
                            ),
                        "key_skills": "Relevant skills",
                        "contact_email": "Email",
                        "manager_name": "Manager",
                    },
                )

        return

    # ---------------------------------------------------------------
    # AI mode
    # ---------------------------------------------------------------

    adapter = get_llm_adapter()

    if adapter is None:
        st.warning(
            "AI is enabled, but Azure OpenAI is not currently configured. "
            "The existing application remains usable, but AI drafting "
            "cannot run until the approved Azure configuration is available."
        )

        st.caption(
            "No API key is used. This integration expects the approved "
            "Microsoft Entra authentication configuration."
        )

        return

    st.success(
        "AI is enabled. Enter the project request in normal language."
    )

    st.caption(
        "The AI will prepare a draft only. You will review it in "
        "Staffing Request and Resource Requirements before matching."
    )

    examples = [
        (
            "Example 1",
            "We need two Consultants working in the India time zone "
            "for a healthcare analytics project starting 5 October 2026 for 12 weeks. "
            "They should have SQL and Python as mandatory skills, "
            "Power BI would be nice to have, and each person should "
            "be available for 30 hours per week."
        ),
        (
            "Example 2",
            "For a project with client location Germany - Frankfurt "
            "starting 12 October 2026, "
            "we need one Senior Consultant for 20 hours per week. "
            "They must know Databricks and Python and preferably "
            "have Machine Learning experience."
        ),
    ]

    for label, example in examples:
        if st.button(
            label,
            key=f"ai_example_{label.replace(' ', '_')}",
            width="stretch",
        ):
            st.session_state.copilot_query = example

    query = st.text_area(
        "Describe the staffing request",
        value=st.session_state.get(
            "copilot_query",
            "",
        ),
        height=180,
        placeholder=(
            "Example: We need two Consultants in the India time zone "
            "for a 12-week healthcare analytics project..."
        ),
        help=(
            "Describe the project, dates, client location, time zone, "
            "geographic expertise, roles, headcount, weekly hours and skills "
            "in normal language."
        ),
    )

    interpret_clicked = st.button(
        "Interpret request with AI",
        type="primary",
        width="stretch",
        key="interpret_staffing_request",
    )

    if interpret_clicked:
        if not query.strip():
            st.warning(
                "Describe the staffing request first."
            )
        else:
            with st.status(
                "AI is interpreting the request...",
                expanded=True,
            ) as status:
                st.write(
                    "Reading the project requirements..."
                )

                governed_values = governed_llm_values(
                    resources
                )

                try:
                    raw_draft = adapter.draft_staffing_request(
                        query,
                        governed_values,
                    )

                    draft = normalise_llm_draft(
                        raw_draft,
                        resources,
                    )

                    st.session_state.llm_draft = draft
                    st.session_state.llm_draft_source = query
                    st.session_state.llm_summary = None

                    status.update(
                        label="AI interpretation completed",
                        state="complete",
                        expanded=False,
                    )

                except Exception as exc:
                    st.error("AI interpretation could not be completed.")

                    error_text = str(exc)

                    if "No module named 'configs'" in error_text:
                        st.warning(
                            "The approved IQVIA Azure OpenAI configuration is not "
                            "available in this Python environment. No application "
                            "data or deterministic staffing logic was changed."
                        )
                    elif "azure-identity" in error_text:
                        st.warning(
                            "The Azure authentication package is not available "
                            "in this Python environment."
                        )
                    elif "openai" in error_text.lower():
                        st.warning(
                            "The Azure OpenAI client package is not available "
                            "in this Python environment."
                        )
                    else:
                        st.warning(
                            "The AI service could not interpret this request. "
                            "No application data or deterministic staffing logic "
                            "was changed."
                        )

                    with st.expander("Technical details"):
                        st.code(error_text)

    # ---------------------------------------------------------------
    # Draft review
    # ---------------------------------------------------------------

    draft = st.session_state.get(
        "llm_draft"
    )

    if draft:
        st.divider()

        llm_draft_display(draft)

        st.divider()

        st.warning(
            "Review the AI interpretation before applying it. "
            "If anything is wrong, you can correct it after applying "
            "the draft in the normal Staffing Request and Resource Requirements tabs."
        )

        apply_column, discard_column = st.columns(
            [2, 1]
        )

        with apply_column:
            if st.button(
                "Apply draft to Staffing Request & Resource Requirements",
                type="primary",
                width="stretch",
                key="apply_llm_draft",
            ):
                apply_llm_draft_to_request(
                    draft
                )

                st.session_state.llm_draft = None

                st.session_state.page = (
                    "Project Details"
                )

                st.rerun()

        with discard_column:
            if st.button(
                "Discard draft",
                width="stretch",
                key="discard_llm_draft",
            ):
                st.session_state.llm_draft = None
                st.session_state.llm_draft_source = ""
                st.rerun()

    # ---------------------------------------------------------------
    # AI architecture explanation
    # ---------------------------------------------------------------

    with st.expander(
        "How AI works in this application",
        expanded=False,
    ):
        st.markdown(
            """
**AI understands the request. The application decides the staffing.**

1. Azure OpenAI interprets the manager's natural-language request.
2. The response is restricted to the application's governed values.
3. The manager reviews the generated draft.
4. The draft is applied to the normal Staffing Request and Resource Requirements.
5. The manager can change anything before matching.
6. The existing deterministic engine performs eligibility,
   capacity checks and scoring.
7. Recommendations remain controlled by the existing application.
            """
        )



apply_theme()
init_state()

resources = active_resources()

_, confirmed_allocations = load_register(
    REGISTER_PATH,
    resources,
)

capacity_start, capacity_end = capacity_horizon()

capacity = build_weekly_capacity(
    resources=resources,
    allocations=confirmed_allocations,
    start_date=capacity_start,
    end_date=capacity_end,
)

data_source_panel(resources, capacity)

brand_bar()
main_navigation()
request_context_bar()

page = st.session_state.page
if page == "Project Details":
    render_project_brief(resources, capacity)
elif page == "Team & skills":
    render_team_and_skills(resources, capacity)
elif page == "Recommendations":
    render_recommendations(resources, capacity, confirmed_allocations)
elif page == "Capacity & risk":
    render_capacity_and_risk(resources, capacity)
else:
    render_copilot(resources, capacity)
