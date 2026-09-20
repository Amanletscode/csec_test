from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import STANDARD_WEEK_HOURS


OPPORTUNITY_COLUMNS = [
    "Opportunity Number",
    "Project Name",
    "Client",
    "Project Description",
    "Start Date",
    "End Date",
    "Number of Resources Needed",
    "Therapeutic Area",
    "KPI Focus Area",
    "Client Facing?",
    "Client Location",
    "Time Zone",
    "Language Requirement",
    "Travel Requirement",
]

ALLOCATION_COLUMNS = [
    "Employee ID",
    "Employee Name",
    "Opportunity Number",
    "Project Name",
    "Allocation Hours / Week",
    "Allocation %",
    "Allocation Start Date",
    "Allocation End Date",
    "Status",
]


def _dummy_opportunities() -> pd.DataFrame:
    rows = [
        ["OPP-2026-001", "Patient Support Program Analytics", "Axerion Pharma", "Build adherence and abandonment monitoring with patient-level analytics.", "2026-10-01", "2027-03-31", 4, "Oncology", "Adherence | Abandonment | Refill Rate", "Y", "USA - New York", "EST", "English", "Quarterly onsite"],
        ["OPP-2026-002", "Copay Card Optimization", "Northstar Biopharma", "Assess copay enrolment, utilisation and affordability barriers.", "2026-10-15", "2027-02-15", 3, "Immunology", "Copay Utilisation | Enrolment Rate | Conversion", "Y", "USA - Chicago", "CST", "English", "No travel"],
        ["OPP-2026-003", "Oncology Market Share Tracker", "Helix Therapeutics", "Automate market-share and competitor-performance tracking.", "2026-11-01", "2027-06-30", 2, "Oncology", "Market Share | NBRx | TRx", "Y", "Germany - Frankfurt", "CET", "English | German", "Up to 10%"],
        ["OPP-2026-004", "Omnichannel HCP Engagement", "Auriga Life Sciences", "Measure channel mix, attribution and HCP response.", "2026-10-20", "2027-04-30", 4, "Cardiology", "HCP Reach | Engagement Rate | Channel Conversion", "Y", "UK - London", "GMT", "English", "Kickoff onsite"],
        ["OPP-2026-005", "Diabetes Forecasting Engine", "Maple BioHealth", "Create brand forecasts with scenario planning.", "2026-11-15", "2027-06-15", 3, "Diabetes", "Forecast Accuracy | Market Growth", "N", "Canada - Toronto", "EST", "English | French", "No travel"],
        ["OPP-2026-006", "Global Patient Services Dashboard", "Orion Health Partners", "Build global operational dashboards for patient services.", "2026-10-01", "2027-09-30", 5, "Rare Disease", "Service Level | Adherence | Case Resolution", "Y", "Singapore", "SGT", "English", "Up to 15%"],
        ["OPP-2026-007", "Rare Disease Patient Journey", "Vela Therapeutics", "Map diagnosis-to-treatment journeys and drop-off points.", "2026-12-01", "2027-03-31", 2, "Rare Disease", "Time to Diagnosis | Persistence | Drop-off Rate", "Y", "France - Paris", "CET", "English | French", "Monthly onsite"],
        ["OPP-2026-008", "Contact Center Performance", "Solstice Pharma", "Analyse abandonment, handling time and resolution.", "2026-10-01", "2027-01-31", 2, "Patient Services", "Call Abandonment | AHT | First Call Resolution", "N", "USA - San Francisco", "PST", "English", "No travel"],
        ["OPP-2026-009", "Obesity Brand Growth Analytics", "Iberia Metabolic Health", "Support GLP-1 launch and territory analytics.", "2026-11-01", "2027-01-31", 3, "Obesity", "Market Share | HCP Reach | Patient Starts", "Y", "Spain - Madrid", "CET", "English | Spanish", "Up to 20%"],
        ["OPP-2026-010", "Next Best Action Engine", "Sakura BioPharma", "Build explainable HCP engagement recommendations.", "2027-01-01", "2027-07-31", 5, "Neurology", "KPI Engagement | Conversion | Incremental Sales", "Y", "Japan - Tokyo", "JST", "English | Japanese", "Quarterly onsite"],
    ]
    return pd.DataFrame(rows, columns=OPPORTUNITY_COLUMNS)


def _dummy_allocations(resources: pd.DataFrame) -> pd.DataFrame:
    assignments = [
        ("OPP-2026-001", "Patient Support Program Analytics", 17.0, "2026-08-01", "2026-12-31"),
        ("OPP-2026-004", "Omnichannel HCP Engagement", 8.5, "2026-09-01", "2026-10-31"),
        ("OPP-2026-009", "Obesity Brand Growth Analytics", 21.25, "2026-09-01", "2027-03-31"),
        ("OPP-2026-003", "Oncology Market Share Tracker", 29.75, "2026-09-01", "2027-02-28"),
        ("OPP-2026-002", "Copay Card Optimization", 25.5, "2026-08-15", "2027-01-31"),
        ("OPP-2026-004", "Omnichannel HCP Engagement", 12.75, "2026-07-15", "2026-11-30"),
        ("OPP-2026-007", "Rare Disease Patient Journey", 25.5, "2026-09-01", "2027-02-28"),
        ("OPP-2026-005", "Diabetes Forecasting Engine", 17.0, "2026-08-01", "2027-03-31"),
        ("OPP-2026-006", "Global Patient Services Dashboard", 34.0, "2026-09-01", "2027-06-30"),
        ("OPP-2026-008", "Contact Center Performance", 17.0, "2026-08-01", "2026-12-31"),
        ("OPP-2026-010", "Next Best Action Engine", 8.5, "2026-09-01", "2027-07-31"),
        ("OPP-2026-008", "Contact Center Performance", 8.5, "2026-09-01", "2026-11-30"),
    ]
    # A deterministic random sample looks like real historical staffing rather
    # than assigning EMP-1001, EMP-1002, EMP-1003 in sequence. Repeated people
    # demonstrate a 42.5-hour week split across multiple projects.
    sampled = resources.sample(
        n=min(8, len(resources)), random_state=20260918
    ).reset_index(drop=True)
    person_slots = [0, 1, 2, 3, 4, 0, 5, 6, 7, 1, 2, 6]
    rows = []
    for index, assignment in enumerate(assignments):
        opportunity, project, allocation_hours, start, end = assignment
        person = sampled.iloc[person_slots[index] % len(sampled)]
        allocation_pct = round(allocation_hours / STANDARD_WEEK_HOURS * 100, 1)
        rows.append([
            str(person.resource_id),
            str(person.resource_name),
            opportunity,
            project,
            allocation_hours,
            allocation_pct,
            start,
            end,
            "Confirmed",
        ])
    return pd.DataFrame(rows, columns=ALLOCATION_COLUMNS)


def _write_register(path: Path, opportunities: pd.DataFrame, allocations: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.stem + ".tmp.xlsx")
    with pd.ExcelWriter(temporary, engine="openpyxl") as writer:
        opportunities[OPPORTUNITY_COLUMNS].to_excel(
            writer, sheet_name="Opportunities", index=False
        )
        allocations[ALLOCATION_COLUMNS].to_excel(
            writer, sheet_name="Allocations", index=False
        )
        for sheet_name, frame in [
            ("Opportunities", opportunities),
            ("Allocations", allocations),
        ]:
            worksheet = writer.book[sheet_name]
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for column_index, column_name in enumerate(frame.columns, start=1):
                width = min(
                    45,
                    max(
                        len(str(column_name)) + 2,
                        max((len(str(value)) for value in frame[column_name].head(200)), default=0)
                        + 2,
                    ),
                )
                worksheet.column_dimensions[
                    worksheet.cell(1, column_index).column_letter
                ].width = width
    temporary.replace(path)


def ensure_register(path: Path, resources: pd.DataFrame) -> None:
    if path.exists():
        return
    _write_register(path, _dummy_opportunities(), _dummy_allocations(resources))


def load_register(path: Path, resources: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    ensure_register(path, resources)
    book = pd.read_excel(path, sheet_name=None)
    opportunities = book.get(
        "Opportunities", pd.DataFrame(columns=OPPORTUNITY_COLUMNS)
    ).reindex(columns=OPPORTUNITY_COLUMNS)
    allocations = book.get("Allocations", pd.DataFrame(columns=ALLOCATION_COLUMNS))
    if "Allocation Hours / Week" not in allocations:
        allocation_pct = pd.to_numeric(
            allocations.get("Allocation %", 0), errors="coerce"
        ).fillna(0.0)
        allocations["Allocation Hours / Week"] = (
            allocation_pct / 100 * STANDARD_WEEK_HOURS
        ).round(2)
    allocations = allocations.reindex(columns=ALLOCATION_COLUMNS)
    return opportunities, allocations


def apply_confirmed_allocations(
    capacity: pd.DataFrame,
    allocations: pd.DataFrame,
) -> pd.DataFrame:
    """Reduce baseline weekly capacity by overlapping confirmed allocations."""
    adjusted = capacity.copy()
    adjusted["resource_id"] = adjusted["resource_id"].astype(str)
    adjusted["week_start"] = pd.to_datetime(
        adjusted["week_start"], errors="coerce"
    ).dt.normalize()
    adjusted["available_capacity_pct"] = pd.to_numeric(
        adjusted["available_capacity_pct"], errors="coerce"
    ).astype(float)

    if allocations is None or allocations.empty:
        return adjusted

    confirmed = allocations[
        allocations["Status"].fillna("").astype(str).str.casefold().eq("confirmed")
    ].copy()
    for _, row in confirmed.iterrows():
        employee_id = str(row["Employee ID"])
        hours = pd.to_numeric(row["Allocation Hours / Week"], errors="coerce")
        if pd.isna(hours):
            allocation_pct = pd.to_numeric(row["Allocation %"], errors="coerce")
        else:
            allocation_pct = float(hours) / STANDARD_WEEK_HOURS * 100
        start = pd.to_datetime(row["Allocation Start Date"], errors="coerce")
        end = pd.to_datetime(row["Allocation End Date"], errors="coerce")
        if pd.isna(allocation_pct) or pd.isna(start) or pd.isna(end):
            continue
        overlaps = (
            adjusted["resource_id"].eq(employee_id)
            & adjusted["week_start"].le(end.normalize())
            & (adjusted["week_start"] + pd.Timedelta(days=6)).ge(start.normalize())
        )
        adjusted.loc[overlaps, "available_capacity_pct"] = (
            adjusted.loc[overlaps, "available_capacity_pct"] - float(allocation_pct)
        ).clip(lower=0.0)
    return adjusted


def append_confirmed_allocations(
    path: Path,
    resources: pd.DataFrame,
    request: dict,
    selected: pd.DataFrame,
) -> dict:
    """Append one opportunity and selected resource allocations idempotently."""
    opportunities, allocations = load_register(path, resources)
    opportunity_number = str(request["request_id"]).strip()

    opportunity_added = 0
    if not opportunities["Opportunity Number"].astype(str).eq(opportunity_number).any():
        opportunity = {
            "Opportunity Number": opportunity_number,
            "Project Name": request.get("project_name", "Untitled project"),
            "Client": request.get("client", "Not specified"),
            "Project Description": request.get(
                "project_description", request.get("project_name", "")
            ),
            "Start Date": str(request["start_date"]),
            "End Date": str(request["end_date"]),
            "Number of Resources Needed": sum(
                int(role.get("headcount", 0)) for role in request.get("role_mix", [])
            ),
            "Therapeutic Area": request.get("therapeutic_area", "Not specified"),
            "KPI Focus Area": request.get("kpi_focus_area", "Not specified"),
            "Client Facing?": request.get("client_facing", "N"),
            "Client Location": request.get(
                "client_location",
                " | ".join(request.get("allowed_locations") or ["Not specified"]),
            ),
            "Time Zone": " | ".join(request.get("time_zones") or ["Not specified"]),
            "Language Requirement": " | ".join(
                request.get("languages") or ["Not specified"]
            ),
            "Travel Requirement": request.get("travel_requirement", "No travel"),
        }
        opportunities = pd.concat(
            [opportunities, pd.DataFrame([opportunity])], ignore_index=True
        )
        opportunity_added = 1

    existing_keys = set(
        zip(
            allocations["Employee ID"].astype(str),
            allocations["Opportunity Number"].astype(str),
        )
    )
    allocation_rows = []
    skipped = 0
    for _, person in selected.iterrows():
        key = (str(person.resource_id), opportunity_number)
        if key in existing_keys:
            skipped += 1
            continue
        allocation_rows.append(
            {
                "Employee ID": str(person.resource_id),
                "Employee Name": str(person.resource_name),
                "Opportunity Number": opportunity_number,
                "Project Name": request.get(
                    "project_name",
                    "Untitled project",
                ),
                "Allocation Hours / Week": float(
                    person["requested_allocation_hours"]
                ),
                "Allocation %": round(
                    float(person["requested_allocation_pct"]),
                    1,
                ),
                "Allocation Start Date": str(request["start_date"]),
                "Allocation End Date": str(request["end_date"]),
                "Status": "Confirmed",
            }
        )
        existing_keys.add(key)
    if allocation_rows:
        allocations = pd.concat(
            [allocations, pd.DataFrame(allocation_rows)], ignore_index=True
        )
    _write_register(path, opportunities, allocations)
    return {
        "opportunity_added": opportunity_added,
        "allocations_added": len(allocation_rows),
        "allocations_skipped": skipped,
        "opportunity_number": opportunity_number,
        "path": str(path),
    }
