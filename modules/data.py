from __future__ import annotations

from pathlib import Path
import pandas as pd

from .config import DESIGNATION_TO_GRADE, GRADE_LABELS
from .validation import validate_resources


def read_table(file_or_path, **kwargs) -> pd.DataFrame:
    if file_or_path is None:
        raise FileNotFoundError("No file supplied")
    name = str(getattr(file_or_path, "name", file_or_path)).lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(file_or_path, **kwargs)
    return pd.read_csv(file_or_path, **kwargs)


def _sheet(book: dict, *names):
    lowered = {str(k).lower().strip(): v for k, v in book.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def load_workbook(file_obj):
    book = pd.read_excel(file_obj, sheet_name=None)
    return _sheet(book, "Resources", "Resource", "Employees", "Employee")


def canonicalize_resources(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    aliases = {
        "employee_id": "resource_id", "emp_id": "resource_id", "name": "resource_name",
        "employee_name": "resource_name", "timezone": "time_zone", "time zone": "time_zone",
        "workcity": "work_city", "work city": "work_city", "city": "work_city",
        "designation": "role_title", "grade_code": "grade",
        "skills_proficiency": "skills", "skill_proficiency": "skills",
        "therapeutic_areas": "domains", "therapeutic_area": "domains",
        "development_interest": "development_interests", "manager": "manager_name",
        "email": "contact_email", "work_email": "contact_email",
    }
    for old, new in aliases.items():
        if old in out.columns and new not in out.columns:
            out[new] = out[old]
    defaults = {
        "resource_id": "", "resource_name": "", "team": "Unassigned", "grade": 130,
        "role_title": "",
        # Work country remains the resource-level location used by travel logic.
        # Work city is kept separately so it is never confused with geography expertise.
        "location": "Unknown", "work_city": "", "time_zone": "Unknown", "languages": "English",
        "skills": "", "domains": "", "development_interests": "", "years_experience": 0,
        "delivery_rating": 0, "profile_updated": pd.Timestamp.today().date(),
        "manager_name": "Not provided", "manager_email": "", "contact_email": "",
        "geography_expertise": "", "project_expertise": "", "expertise_summary": "",
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default
    out["resource_id"] = out["resource_id"].astype(str).str.strip()
    out["resource_name"] = out["resource_name"].fillna("").astype(str).str.strip()
    raw_grade = out["grade"].copy()
    out["grade"] = pd.to_numeric(raw_grade, errors="coerce")
    text_grade = raw_grade.astype(str).map(DESIGNATION_TO_GRADE)
    out["grade"] = out["grade"].fillna(text_grade)
    role_from_grade = out["grade"].map(GRADE_LABELS).replace(
        {"Analyst / Associate Consultant": "Analyst"}
    )
    role = out["role_title"].fillna("").astype(str).str.strip()
    out["role_title"] = role.where(role.ne(""), role_from_grade)
    out["profile_updated"] = pd.to_datetime(out["profile_updated"], errors="coerce")
    out["location"] = out["location"].fillna("").astype(str).str.strip()
    out["work_city"] = out["work_city"].fillna("").astype(str).str.strip()
    out["time_zone"] = out["time_zone"].fillna("").astype(str).str.strip()
    return out



def dataset_health(resources) -> dict:
    rr = validate_resources(resources)
    return {
        "resources_ok": rr.ok,
        "resources_errors": rr.errors,
        "resources_warnings": rr.warnings,
        "resource_count": len(resources),
    }