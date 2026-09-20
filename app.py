from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from tracemalloc import start

import pandas as pd
import plotly.express as px
import streamlit as st

import hashlib
import json

from modules.config import (
    DATA_VERSION,
    DEFAULT_WEIGHTS,
    DESIGNATIONS,
    DESIGNATION_TO_GRADE,
    KPI_FOCUS_AREAS,
    LANGUAGES,
    LOCATIONS,
    PROFICIENCY,
    PROFICIENCY_LABELS,
    SKILL_CATALOG,
    STANDARD_WEEK_HOURS,
    THERAPEUTIC_AREAS,
    TIME_ZONES,
    TRAVEL_REQUIREMENTS,
)
from modules.data import (
    canonicalize_capacity,
    canonicalize_resources,
    dataset_health,
    load_demo_data,
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
    initial_sidebar_state="expanded",
)

DATA_DIR = Path(__file__).parent / "data"
REGISTER_PATH = DATA_DIR / "staffing_register.xlsx"
DATA_DIR.mkdir(exist_ok=True)
if not (DATA_DIR / "resources.csv").exists():
    write_demo_data(DATA_DIR)

WORKFLOW_PAGES = ["Project brief", "Team & skills", "Recommendations"]
TOOL_PAGES = ["Capacity & risk", "Ask Copilot"]
PAGES = WORKFLOW_PAGES + TOOL_PAGES
NAV_LABELS = {page: page for page in PAGES}
NAV_HELP = {
    "Project brief": "Delivery window, eligibility rules and opportunity record.",
    "Team & skills": "Headcount per designation, required skills and ranking weights.",
    "Recommendations": "People who meet every requirement, ranked by fit.",
    "Capacity & risk": "Unused capacity, coverage risk and the weekly capacity trend.",
    "Ask Copilot": "Search in plain language, for example: Tableau consultants in India.",
}


@st.cache_data(max_entries=3)
def load_cached_resources(data_dir: str, data_version: str):
    del data_version

    resources_path = Path(data_dir) / "resources.csv"

    resources = pd.read_csv(resources_path)

    return canonicalize_resources(resources)


def active_resources() -> pd.DataFrame:
    if st.session_state.uploaded_data is not None:
        uploaded_resources, _ = st.session_state.uploaded_data
        return uploaded_resources

    return load_cached_resources(
        str(DATA_DIR),
        DATA_VERSION,
    )

def capacity_horizon() -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Return the planning horizon used to build weekly capacity.

    The application keeps a 30-week rolling planning horizon, matching
    the historical capacity dataset structure.
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
        .block-container {max-width:1420px; padding-top:1.1rem; padding-bottom:3.5rem;}
        h1, h2, h3 {color:var(--ink); letter-spacing:-.015em;}
        .brandbar {display:flex; justify-content:space-between; align-items:flex-end;
            padding-bottom:.7rem; border-bottom:1px solid var(--line); margin-bottom:.9rem;}
        .brandbar .name {font-size:1.15rem; font-weight:700; color:var(--ink);}
        .brandbar .sub {font-size:.85rem; color:var(--muted);}
        .brandbar .ctx {text-align:right; font-size:.85rem; color:var(--muted);}
        .brandbar .ctx b {color:var(--ink);}
        .pagehead {margin:.4rem 0 1.1rem;}
        .pagehead h1 {font-size:1.5rem; margin:0;}
        .pagehead p {margin:.3rem 0 0; color:var(--muted); max-width:70ch;}
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
        .stButton > button {border-radius:8px; min-height:2.6rem; font-weight:600;}
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
    if page in {"Project brief", "Team & skills"}:
        st.session_state.results = None
        st.session_state.result_request_fingerprint = None

    st.session_state.page = page
    st.rerun()


def request_defaults() -> dict:
    return {
        "request_id": "OPP-2026-011",
        "project_name": "Healthcare analytics delivery",
        "start_date": date.today() + timedelta(days=7),
        "end_date": date.today() + timedelta(days=84),
        "allowed_locations": ["India"],
        "time_zones": ["Asia/Kolkata"],
        "languages": ["English"],
        "allowed_teams": [],
        "client": "Axerion Pharma",
        "project_description": "Build patient-level analytics and reporting for delivery teams.",
        "therapeutic_area": "Oncology",
        "kpi_focus_areas": ["Adherence", "Patient Reach", "Service Level"],
        "kpi_focus_area": "Adherence | Patient Reach | Service Level",
        "client_facing": "Y",
        "client_location": "India",
        "travel_requirement": "No travel",
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
        "page": "Project brief",
        "request": request_defaults(),
        "results": None,
        "result_request_fingerprint": None,
        "chat_history": [],
        "editor_version": 0,
        "uploaded_data": None,
        "last_register_result": None,
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



def brand_bar() -> None:
    request = st.session_state.request
    status = "Not run yet"
    if st.session_state.results is not None:
        diagnostics = st.session_state.results.diagnostics
        status = (
            f"{diagnostics.get('fillable_slots', 0)} of "
            f"{diagnostics.get('requested_slots', 0)} roles fillable"
        )
    st.markdown(
        f"""
        <div class="brandbar">
            <div>
                <div class="name">CSEC Resource Manager</div>
                <div class="sub">Plan project staffing, check real availability and find capability.</div>
            </div>
            <div class="ctx">
                <b>{request.get('request_id', 'Draft')}</b> · {request.get('project_name', 'Untitled project')}<br>
                Match status: {status}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main_navigation() -> None:
    columns = st.columns(len(PAGES), gap="small")
    for column, page in zip(columns, PAGES):
        is_active = st.session_state.page == page
        if column.button(
            NAV_LABELS[page],
            key=f"nav_{page}",
            help=NAV_HELP[page],
            width="stretch",
            type="primary" if is_active else "secondary",
        ):
            navigate(page)
    st.write("")


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
            f"Active dataset: {len(resources):,} people · {len(capacity):,} weekly capacity rows."
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
                "The workbook needs a Resources sheet and a Capacity sheet. "
                "Capacity must contain resource_id, week_start and available_capacity_pct."
            ),
        )
        if uploaded is not None and st.button("Load this workbook", key="load_workbook"):
            try:
                raw_resources, raw_capacity = load_workbook(uploaded)
                if raw_resources is None or raw_capacity is None:
                    st.error("Both a Resources sheet and a Capacity sheet are required.")
                else:
                    st.session_state.uploaded_data = (
                        canonicalize_resources(raw_resources),
                        canonicalize_capacity(raw_capacity),
                    )
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
        health = dataset_health(resources, capacity)
        problems = health["resources_errors"] + health["capacity_errors"]
        if problems:
            for problem in problems[:5]:
                st.error(problem)
        else:
            st.success("All data quality checks passed.")
    with st.expander("Upload schema", expanded=False):
        st.caption("Workbook sheet: Resources (one row per person)")
        st.code(
            "resource_id, resource_name, team, grade, role_title, location, "
            "time_zone, languages, skills, domains, development_interests, "
            "years_experience, delivery_rating, profile_updated",
            language=None,
        )
        st.caption("Skills use Skill:Level separated by pipes. Example:")
        st.code("SQL:3|Python:2|Power BI:3", language=None)
        st.caption("Workbook sheet: Capacity (one row per person per week)")
        st.code(
            "resource_id, week_start, available_capacity_pct",
            language=None,
        )
        st.caption(
            f"`available_capacity_pct` is converted using {STANDARD_WEEK_HOURS:g} hours = 100%."
        )
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
        "role_title": st.column_config.TextColumn("Designation"),
        "grade": st.column_config.NumberColumn("Grade"),
        "team": st.column_config.TextColumn("Team"),
        "location": st.column_config.TextColumn("Country"),
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


def requirement_recap(request: dict) -> None:
    with st.expander("Requirements applied to this shortlist", expanded=False):
        left, right = st.columns(2)
        with left:
            st.markdown("**Delivery constraints**")
            st.write(
                f"- Dates: {request['start_date']:%d %b %Y} to "
                f"{request['end_date']:%d %b %Y}\n"
                f"- Country: {', '.join(request.get('allowed_locations') or ['Any'])}\n"
                f"- Time zone: {', '.join(request.get('time_zones') or ['Any'])}\n"
                f"- Language: {', '.join(request.get('languages') or ['Any'])}\n"
                f"- Specific team: {', '.join(request.get('allowed_teams') or ['Any'])}"
            )
        with right:
            st.markdown("**Role-specific capability**")
            for row in request.get("role_mix", []):
                mandatory = row.get(
                    "mandatory_skills", request.get("mandatory_skills", {})
                )
                preferred = row.get(
                    "preferred_skills", request.get("preferred_skills", {})
                )
                st.write(
                    f"- **{row['headcount']} × {row['designation']}** "
                    f"(grade {row['grade']}, "
                    f"{row.get('allocation_hours', 21.25):.2f}h/week · "
                    f"{row.get('allocation_pct', 50.0):.1f}% availability): "
                    + (
                        ", ".join(
                            f"{skill} · {PROFICIENCY_LABELS[level - 1]}"
                            for skill, level in mandatory.items()
                        )
                        or "No mandatory skills"
                    )
                    + (
                        "; nice to have "
                        + ", ".join(
                            f"{skill} · {PROFICIENCY_LABELS[level - 1]}"
                            for skill, level in preferred.items()
                        )
                        if preferred
                        else ""
                    )
                )
        st.caption("Change these in the project brief or team & skills, then run the match again.")


def render_project_brief(resources: pd.DataFrame, capacity: pd.DataFrame) -> None:
    page_header(
        "Project brief",
        "Delivery window, eligibility rules and the opportunity record written to the register.",
    )
    request = st.session_state.request
    st.caption(r"\* required")

    engagement_column, window_column = st.columns(2, gap="large")
    with engagement_column:
        with card("Engagement"):
            request_id = st.text_input(
                "Opportunity number *",
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
                "Project name *",
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
        with card("Delivery window"):
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
                "Client facing",
                ["Y", "N"],
                index=0 if request.get("client_facing", "Y") == "Y" else 1,
                horizontal=True,
                help="Identifies whether the allocated people will work directly with the client.",
            )

    eligibility_column, record_column = st.columns(2, gap="large")
    with eligibility_column:
        with card("Eligibility rules"):
            locations = st.multiselect(
                "Work country *",
                LOCATIONS,
                default=[x for x in request.get("allowed_locations", []) if x in LOCATIONS],
                placeholder="Choose one or more countries",
                help="Where the person works. Never widened to a region.",
            )
            zones = st.multiselect(
                "Time zone",
                TIME_ZONES,
                default=[x for x in request.get("time_zones", []) if x in TIME_ZONES],
                placeholder="Any time zone",
                help="If selected, a person must work in one of these time zones.",
            )
            languages = st.multiselect(
                "Language",
                LANGUAGES,
                default=[x for x in request.get("languages", []) if x in LANGUAGES],
                placeholder="Any language",
                help="A person must speak every language selected.",
            )
            team_options = sorted(resources.team.dropna().astype(str).unique())
            specific_teams = st.multiselect(
                "Specific team",
                team_options,
                default=[x for x in request.get("allowed_teams", []) if x in team_options],
                placeholder="All teams",
                help="An exact eligibility filter. Team is never scored.",
            )
    with record_column:
        with card("Opportunity record"):
            kpi_focus_areas = st.multiselect(
                "KPI focus area *",
                KPI_FOCUS_AREAS,
                default=[
                    x for x in request.get("kpi_focus_areas", []) if x in KPI_FOCUS_AREAS
                ],
                placeholder="Choose the KPIs this work moves",
                help="The business measures this opportunity is expected to improve.",
            )
            location_column, travel_column = st.columns(2)
            with location_column:
                client_location = st.text_input(
                    "Client location",
                    value=request.get("client_location", ""),
                    placeholder="USA - New York",
                    help="Where the client team is based; this is recorded but is not a work-country gate.",
                )
            with travel_column:
                travel_requirement = st.selectbox(
                    "Travel requirement",
                    TRAVEL_REQUIREMENTS,
                    index=(
                        TRAVEL_REQUIREMENTS.index(request["travel_requirement"])
                        if request.get("travel_requirement") in TRAVEL_REQUIREMENTS
                        else 0
                    ),
                    help="Expected onsite travel for people allocated to the opportunity.",
                )
            project_description = st.text_area(
                "Project description",
                value=request.get("project_description", ""),
                height=122,
                placeholder="What the team will build or analyse.",
                help="A concise delivery summary written to the opportunity register.",
            )

    note(
        "Country, specific team, time zone, language, designation, mandatory skills and weekly "
        "availability are strict rules. A strong score can never compensate for one of them."
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
    if not locations:
        problems.append("At least one work country is required.")
    if not kpi_focus_areas:
        problems.append("At least one KPI focus area is required.")
    if end_date < start_date:
        problems.append("The end date is before the start date.")
    if (end_date - start_date).days > 730:
        problems.append("A request cannot be longer than two years.")
    for problem in problems:
        st.warning(problem)

    if st.button(
        "Save and continue",
        type="primary",
        disabled=bool(problems),
    ):
        st.session_state.request = request | {
            "request_id": request_id.strip(),
            "project_name": project_name.strip(),
            "start_date": start_date,
            "end_date": end_date,
            "allowed_locations": locations,
            "allowed_teams": specific_teams,
            "time_zones": zones,
            "languages": languages,
            "client": client.strip(),
            "project_description": project_description.strip() or project_name.strip(),
            "therapeutic_area": therapeutic_area,
            "kpi_focus_areas": kpi_focus_areas,
            "kpi_focus_area": " | ".join(kpi_focus_areas),
            "client_facing": client_facing,
            "client_location": client_location.strip() or "Not specified",
            "travel_requirement": travel_requirement,
        }
        navigate("Team & skills")


def render_team_and_skills(resources: pd.DataFrame, capacity: pd.DataFrame) -> None:
    page_header(
        "Team & skills",
        "Headcount per designation, the skills each role must bring, and how people are ranked.",
    )
    request = st.session_state.request
    version = st.session_state.editor_version

    st.subheader("Roles required *")
    st.caption("Use the last row to add another designation.")
    edited_roles = st.data_editor(
        role_rows(request),
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        key=f"role_editor_{version}",
        column_config={
            "Designation": st.column_config.SelectboxColumn(
                "Designation",
                options=DESIGNATIONS,
                required=True,
                help="Grade is set automatically: 130 Analyst and Associate Consultant, 140 Consultant, then +10 per level.",
            ),
            "People required": st.column_config.NumberColumn(
                "People required",
                min_value=1,
                max_value=50,
                step=1,
                required=True,
                help="How many people you need at this designation.",
            ),
            "Weekly hours/person": st.column_config.NumberColumn(
                "Weekly hours/person",
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
            '<div class="preview">Requesting '
            + ", ".join(
                f"{row['headcount']} × {row['designation']} "
                f"(grade {row['grade']}, "
                f"{row['allocation_hours']:.2f}h/week · "
                f"{row['allocation_pct']:.1f}% availability)"
                for row in parsed_roles
            )
            + "</div>",
            unsafe_allow_html=True,
        )

    st.divider()
    st.subheader("Skills per role")
    st.caption("Each designation carries its own mandatory and nice-to-have skills.")
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
        with st.expander(
            f"{designation} · grade {role['grade']} · {role['headcount']} needed",
            expanded=True,
        ):
            mandatory_column, preferred_column = st.columns(2, gap="large")
            with mandatory_column:
                st.markdown("**Mandatory**")
                mandatory_rows = st.data_editor(
                    rows_from_skills(mandatory_default),
                    num_rows="dynamic",
                    hide_index=True,
                    width="stretch",
                    key=f"mandatory_{designation}_{version}",
                    column_config={
                        "Skill": st.column_config.SelectboxColumn(
                            "Skill",
                            options=SKILL_CATALOG,
                            required=True,
                            help="A capability every eligible person must have.",
                        ),
                        "Proficiency": st.column_config.SelectboxColumn(
                            "Required proficiency",
                            options=PROFICIENCY_LABELS,
                            required=True,
                            help="Minimum governed proficiency; candidates below it are excluded.",
                        ),
                    },
                )
            with preferred_column:
                st.markdown("**Nice to have**")
                preferred_rows = st.data_editor(
                    rows_from_skills(preferred_default),
                    num_rows="dynamic",
                    hide_index=True,
                    width="stretch",
                    key=f"preferred_{designation}_{version}",
                    column_config={
                        "Skill": st.column_config.SelectboxColumn(
                            "Skill",
                            options=SKILL_CATALOG,
                            required=True,
                            help="A capability that improves ranking but is not mandatory.",
                        ),
                        "Proficiency": st.column_config.SelectboxColumn(
                            "Preferred proficiency",
                            options=PROFICIENCY_LABELS,
                            required=True,
                            help="Preferred proficiency used when ranking eligible people.",
                        ),
                    },
                )
            role_skill_rows[designation] = (mandatory_rows, preferred_rows)

    st.divider()
    st.subheader("Ranking weights")
    weight_labels = {
        "mandatory_skills": "Mandatory skills (%)",
        "preferred_skills": "Nice-to-have skills (%)",
        "proficiency": "Proficiency depth (%)",
        "capacity": "Capacity fit (%)",
    }
    custom_weights = st.checkbox(
        "Set scoring weights manually",
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
            " · ".join(
                f"{weight_labels[key].removesuffix(' (%)')} {value:.0%}"
                for key, value in DEFAULT_WEIGHTS.items()
            )
        )

    st.divider()
    back_column, run_column = st.columns([1, 2])
    with back_column:
        if st.button("Back to project brief", width="stretch"):
            navigate("Project brief")
    with run_column:
        if st.button(
            "Find matching people",
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
            health = dataset_health(resources, capacity)
            errors = health["resources_errors"] + health["capacity_errors"] + report.errors
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

                st.session_state.page = "Recommendations"
                st.rerun()

def render_recommendations(
    resources: pd.DataFrame, capacity: pd.DataFrame
) -> None:
    page_header(
        "Recommendations",
        "People who meet every requirement, combined across all requested roles.",
    )
    result = st.session_state.results
    request = st.session_state.request

    current_fingerprint = request_fingerprint(request)
    stored_fingerprint = st.session_state.get(
        "result_request_fingerprint"
    )

    if (
        result is None
        or stored_fingerprint != current_fingerprint
    ):
        st.info(
            "No current match is available for the current requirements. "
            "Go to Team & skills and run the match again."
        )
        if st.button("Go to Team & skills", type="primary"):
            navigate("Team & skills")
        return

    diagnostics = result.diagnostics
    metrics = st.columns(4)
    metrics[0].metric("Roles requested", diagnostics.get("requested_slots", 0))
    metrics[1].metric("Roles you can fill", diagnostics.get("fillable_slots", 0))
    metrics[2].metric("People assessed", diagnostics.get("resources_assessed", 0))
    metrics[3].metric("Weeks checked", diagnostics.get("request_window_weeks", 0))

    st.caption(
        "Requirement checks: country · specific team (when selected) · time zone · language · exact designation/grade · "
        "mandatory skill proficiency · complete weekly capacity · requested allocation."
    )
    requirement_recap(request)

    roles = diagnostics.get("roles", [])
    if not roles:
        st.warning("No valid role was requested. Add a designation in team & skills.")
        return

    st.caption(
        "Role coverage: "
        + " | ".join(
            f"{role['designation']}: {role['eligible']} recommended for {role['requested']} requested"
            for role in roles
        )
    )
    eligible = result.table[result.table.status.eq("Eligible")].copy()

    if eligible.empty:
        st.error("Nobody meets every requirement across the requested roles.")
        st.caption(
            "Nothing was relaxed automatically. The profiles below failed only one or two rules, "
            "so you can decide whether to change a requirement."
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
                    "resource_name": "Person",
                    "role_title": "Designation",
                    "location": "Country",
                    "minimum_available_hours": st.column_config.NumberColumn(
                        "Lowest weekly free hours", format="%.2f h"
                    ),
                    "exclusion_reasons": "Why they were excluded",
                },
            )
        if st.button("Adjust the requirement", type="primary"):
            navigate("Team & skills")
        return

    eligible = eligible.sort_values(["requested_designation", "rank", "resource_name"])
    eligible["minimum_available_hours"] = (
        eligible["minimum_available_pct"] / 100 * STANDARD_WEEK_HOURS
    )
    st.markdown("#### Combined recommendation list")
    st.dataframe(
        eligible[
            [
                "requested_designation",
                "rank",
                "resource_name",
                "grade",
                "team",
                "location",
                "time_zone",
                "total_score",
                "minimum_available_hours",
            ]
        ].sort_values("rank"),
        hide_index=True,
        width="stretch",
        column_config=shortlist_columns()
        | {
            "requested_designation": st.column_config.TextColumn("Requested role")
        },
    )

    st.divider()
    eligible = eligible.copy()
    eligible["candidate_key"] = (
        eligible.role_key.astype(str) + "|" + eligible.resource_id.astype(str)
    )
    person_id = st.selectbox(
        "Look at one person in detail",
        eligible.candidate_key.tolist(),
        format_func=lambda key: (
            f"{eligible[eligible.candidate_key.eq(key)].iloc[0].resource_name} — "
            f"{eligible[eligible.candidate_key.eq(key)].iloc[0].requested_designation}"
        ),
    )
    person = eligible[eligible.candidate_key.eq(person_id)].iloc[0]
    detail_column, score_column = st.columns([1.4, 1], gap="large")
    with detail_column:
        with st.container(border=True):
            st.markdown(f"### {person.resource_name}")
            st.caption(
                f"{person.role_title} · grade {person.grade} · {person.team} · "
                f"{person.location} · {person.time_zone}"
            )
            st.write(
                f"**Email:** {person.contact_email or 'Not provided'}  \n"
                f"**Manager:** {person.manager_name}"
                + (f" ({person.manager_email})" if person.manager_email else "")
            )
        st.markdown("#### Skills against your request")
        source = resources[resources.resource_id.astype(str).eq(str(person.resource_id))].iloc[0]
        candidate_skills = parse_skill_string(source.skills)
        mandatory_for_role = person.get(
            "requested_mandatory_skills", request.get("mandatory_skills", {})
        )
        preferred_for_role = person.get(
            "requested_preferred_skills", request.get("preferred_skills", {})
        )
        combined = mandatory_for_role | preferred_for_role
        if combined:
            comparison = pd.DataFrame(
                [
                    {
                        "Skill": skill,
                        "You asked for": PROFICIENCY_LABELS[level - 1],
                        "This person has": (
                            PROFICIENCY_LABELS[candidate_skills[skill] - 1]
                            if skill in candidate_skills
                            else "Not listed"
                        ),
                        "Type": (
                            "Mandatory"
                            if skill in mandatory_for_role
                            else "Nice to have"
                        ),
                    }
                    for skill, level in combined.items()
                ]
            )
            st.dataframe(comparison, hide_index=True, width="stretch")
        else:
            st.caption("No skills were requested, so ranking used available capacity only.")
    with score_column:
        st.metric("Overall fit", f"{person.total_score:.1f} / 100")
        components = pd.DataFrame(
            {
                "Component": [
                    name.replace("_", " ").capitalize() for name in person.score_components
                ],
                "Points": list(person.score_components.values()),
            }
        )
        figure = px.bar(components, x="Points", y="Component", orientation="h")
        figure.update_layout(height=280, margin=dict(l=0, r=10, t=10, b=0))
        st.plotly_chart(figure, width="stretch")
        st.caption("Weighted points contributing to the overall fit.")

    st.divider()
    st.markdown("#### Confirm resource allocation")
    st.caption(
        "Select only the people approved by the manager. Confirmation appends one row to the "
        "Opportunities sheet and one row per selected person to the Allocations sheet."
    )
    selected_keys = st.multiselect(
        "Approved people",
        eligible.candidate_key.tolist(),
        format_func=lambda key: (
            f"{eligible[eligible.candidate_key.eq(key)].iloc[0].resource_name} — "
            f"{eligible[eligible.candidate_key.eq(key)].iloc[0].requested_designation}"
        ),
        placeholder="Select reviewed candidates",
        help="You can select fewer people than requested and return later to confirm others.",
    )
    if st.button("Confirm allocation and append to workbook", type="primary"):
        selected = eligible[eligible.candidate_key.isin(selected_keys)]
        if selected.empty:
            st.warning("Select at least one person.")
        else:
            # Recheck against the latest register-adjusted capacity on the
            # confirmation rerun. This prevents a stale shortlist from
            # overbooking someone who was allocated to another project.
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
                    f"{len(blocked)} selected person(s) no longer have enough free hours "
                    "after confirmed allocations and were not allocated."
                )
            if selected.empty:
                st.error("None of the selected people still have enough weekly hours.")
                return
            try:
                register_result = append_confirmed_allocations(
                    REGISTER_PATH, resources, request, selected
                )
                st.session_state.last_register_result = register_result
                st.success(
                    f"Saved {register_result['allocations_added']} allocation row(s) to "
                    f"{REGISTER_PATH.name}."
                )
                if register_result["allocations_skipped"]:
                    st.info(
                        f"{register_result['allocations_skipped']} row(s) already existed and "
                        "were not duplicated."
                    )
            except PermissionError:
                st.error(
                    "The register is open in Excel. Close the workbook, then confirm again."
                )
            except Exception:
                st.error("The allocation register could not be updated safely.")

    if st.session_state.last_register_result:
        opportunities, allocations = load_register(REGISTER_PATH, resources)
        opportunity_number = st.session_state.last_register_result["opportunity_number"]
        st.markdown("##### Rows currently stored for this opportunity")
        st.dataframe(
            allocations[
                allocations["Opportunity Number"].astype(str).eq(opportunity_number)
            ][ALLOCATION_COLUMNS],
            hide_index=True,
            width="stretch",
        )


def horizon_availability(capacity: pd.DataFrame, from_date, weeks: int):
    """Per-person availability across a multi-week horizon.

    A person is only credited with sustained capacity when every week in the
    horizon is present in the capacity sheet, matching the matching engine.
    """
    frame = capacity.copy()
    frame["week_start"] = pd.to_datetime(frame["week_start"], errors="coerce").dt.normalize()
    first = pd.Timestamp(from_date).normalize()
    first = first - pd.Timedelta(days=first.weekday())
    last = first + pd.Timedelta(weeks=weeks - 1)
    window = frame[frame.week_start.between(first, last)]
    if window.empty:
        return pd.DataFrame(), []
    grid = window.pivot_table(
        index=window.resource_id.astype(str),
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
    parsed = parse_skill_string(raw)
    ranked = sorted(parsed.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return ", ".join(skill for skill, _ in ranked)


def skill_holders(resources: pd.DataFrame, minimum_level: int) -> dict[str, list[str]]:
    holders: dict[str, list[str]] = {}
    for row in resources.itertuples(index=False):
        for skill, level in parse_skill_string(row.skills).items():
            if level >= minimum_level:
                holders.setdefault(skill, []).append(str(row.resource_id))
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
        st.info("The capacity sheet holds no weeks in this horizon.")
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
        "Capacity & risk",
        "Portfolio view of unused capacity, thin capability coverage and the weekly "
        "capacity trend, before a request exists.",
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
        st.info("The capacity sheet holds no weeks in this horizon. Move the start week.")
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
        f"{week_columns[-1]:%d %b %Y} · {len(pool):,} people · a week missing from the "
        "capacity sheet counts as unavailable."
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


def render_copilot(resources: pd.DataFrame, capacity: pd.DataFrame) -> None:
    page_header(
        "Ask Copilot",
        "Search for resource in plain language."
        ,
    )
    use_llm = st.checkbox(
        "Use AI to interpret this request",
        value=False,
        help=(
            "Uses Azure OpenAI only to understand natural-language wording. "
            "Existing deterministic matching, eligibility rules, capacity checks, "
            "and scoring remain unchanged."
        ),
    )

    llm_adapter = None

    if use_llm:
        candidate_adapter = build_azure_llm_adapter()

        if candidate_adapter.configured:
            llm_adapter = candidate_adapter
            st.caption("AI interpretation: Azure OpenAI")
        else:
            st.warning(
                "Azure OpenAI is not configured. "
                "The application will use deterministic keyword interpretation."
            )
    examples = [
        "Consultants with SQL and Python in Germany",
        "GenAI experts in India",
        "Power BI people in India with 21-25 hours free from 2026-09-21",
    ]
    example_columns = st.columns(len(examples))
    for index, example in enumerate(examples):
        if example_columns[index].button(
            example, key=f"example_{index}", width="stretch", help="Use this example question."
        ):
            st.session_state.copilot_query = example

    query = st.text_input(
        "What are you looking for?",
        value=st.session_state.get("copilot_query", ""),
        placeholder="For example: Tableau consultants in India with 21 hours free from 2026-09-21",
        help=(
            "Mention skills, country, designation, weekly free hours and a start date. "
            "Percentage availability is also accepted for compatibility."
        ),
    )
    if st.button("Search", type="primary"):
        if not query.strip():
            st.warning("Type a question first, or choose one of the examples above.")
        else:
            intent, found = discovery_search(
                resources,
                capacity,
                query,
                limit=25,
                llm_adapter=llm_adapter,
            )
            st.session_state.chat_history.insert(
                0, {"query": query, "intent": intent, "rows": found}
            )

    for item in st.session_state.chat_history[:3]:
        with st.container(border=True):
            st.markdown(f"**You asked:** {item['query']}")
            chips = describe_filters(item["intent"])
            if chips:
                st.caption("Understood as — " + " | ".join(chips))
            found = item["rows"]
            if found.empty:
                st.info(
                    "Nobody matched every part of that question. Try removing one condition, "
                    "or check the spelling of the skill or country."
                )
                continue
            found = found.copy()
            if "minimum_available_pct" in found:
                found["minimum_available_hours"] = (
                    found["minimum_available_pct"] / 100 * STANDARD_WEEK_HOURS
                )
            st.caption(f"{len(found)} people found.")
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
                    "minimum_available_hours": st.column_config.NumberColumn(
                        "Free weekly hours", format="%.2f h"
                    ),
                    "key_skills": "Relevant skills",
                    "contact_email": "Email",
                    "manager_name": "Manager",
                },
            )

    with st.expander("How this will work with an approved LLM", expanded=False):
        st.write(
            "Search currently runs on keywords, so no API key is needed. When an approved model "
            "is available it plugs into the same contract at runtime: it only turns your sentence "
            "into the governed filters shown above. Its output is checked against the catalogue, "
            "it cannot change any eligibility rule or score, and if it fails or times out the "
            "keyword search takes over automatically."
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

page = st.session_state.page
if page == "Project brief":
    render_project_brief(resources, capacity)
elif page == "Team & skills":
    render_team_and_skills(resources, capacity)
elif page == "Recommendations":
    render_recommendations(resources, capacity)
elif page == "Capacity & risk":
    render_capacity_and_risk(resources, capacity)
else:
    render_copilot(resources, capacity)
