from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import pandas as pd

from .config import (
    DESIGNATIONS,
    DESIGNATION_TO_GRADE,
    GRADE_CODES,
    LANGUAGES,
    CLIENT_LOCATION_TO_COUNTRY,
    GEOGRAPHIES,
    LOCATIONS,
    TRAVEL_REQUIREMENTS,
    PROFICIENCY,
    SKILL_ALIASES,
    SKILL_CATALOG,
    STANDARD_WEEK_HOURS,
    TIME_ZONES,
)

@dataclass
class ValidationReport:
    ok: bool
    errors: list[str]
    warnings: list[str]

REQUIRED_RESOURCE_COLUMNS = {
    "resource_id", "resource_name", "team", "grade", "location", "time_zone",
    "languages", "skills", "domains", "development_interests", "years_experience",
    "delivery_rating", "profile_updated",
}


ALIAS_LOWER = {k.lower(): v for k, v in SKILL_ALIASES.items()}


def normalize_skill_name(name: Any) -> str | None:
    if name is None:
        return None
    raw = str(name).strip()
    if not raw:
        return None
    if raw in SKILL_CATALOG:
        return raw
    return ALIAS_LOWER.get(raw.lower())


def parse_skill_string(value: Any) -> dict[str, int]:
    """Safely parse pipe-delimited `Skill:Level` data. Malformed tokens are ignored."""
    if value is None:
        return {}
    if isinstance(value, dict):
        out: dict[str, int] = {}
        for name, level in value.items():
            canonical = normalize_skill_name(name)
            try:
                lvl = int(float(level))
            except (TypeError, ValueError):
                continue
            if canonical and lvl in PROFICIENCY.values():
                out[canonical] = max(out.get(canonical, 0), lvl)
        return out
    try:
        if pd.isna(value):
            return {}
    except (TypeError, ValueError):
        pass

    out: dict[str, int] = {}
    for token in str(value).replace(";", "|").split("|"):
        token = token.strip()
        if not token or ":" not in token:
            continue
        name, raw_level = token.rsplit(":", 1)
        canonical = normalize_skill_name(name)
        try:
            level = int(float(raw_level.strip()))
        except (TypeError, ValueError):
            continue
        if canonical and level in PROFICIENCY.values():
            out[canonical] = max(out.get(canonical, 0), level)
    return out


def split_pipe(value: Any) -> set[str]:
    if value is None:
        return set()
    try:
        if pd.isna(value):
            return set()
    except (TypeError, ValueError):
        pass
    return {x.strip() for x in str(value).replace(";", "|").split("|") if x.strip()}


def validate_resources(df: pd.DataFrame) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    missing = REQUIRED_RESOURCE_COLUMNS - set(df.columns)
    if missing:
        errors.append(f"Resources file is missing required columns: {', '.join(sorted(missing))}")
        return ValidationReport(False, errors, warnings)
    if df.empty:
        errors.append("Resources dataset is empty.")
        return ValidationReport(False, errors, warnings)
    if df.resource_id.fillna("").astype(str).str.strip().eq("").any():
        errors.append("Every resource must have a non-empty resource_id.")
    if df.resource_name.fillna("").astype(str).str.strip().eq("").any():
        errors.append("Every resource must have a non-empty resource_name.")
    if df.resource_id.astype(str).duplicated().any():
        dup = df.loc[df.resource_id.astype(str).duplicated(keep=False), "resource_id"].astype(str).unique()[:8]
        errors.append(f"Duplicate resource IDs found: {', '.join(dup)}")
    grade_values = pd.to_numeric(df.grade, errors="coerce")
    unknown_grades = sorted(set(grade_values.dropna().astype(int)) - set(GRADE_CODES))
    if grade_values.isna().any():
        errors.append("Resource grade must be a numeric governed grade code.")
    if unknown_grades:
        errors.append(f"Unknown resource grade code(s): {', '.join(map(str, unknown_grades[:8]))}")
    unknown_locations = sorted(set(df.location.dropna().astype(str)) - set(LOCATIONS))
    if unknown_locations:
        warnings.append(f"Unknown location(s) found: {', '.join(unknown_locations[:8])}")
    unknown_zones = sorted(set(df.time_zone.dropna().astype(str)) - set(TIME_ZONES))
    if unknown_zones:
        warnings.append(f"Unknown time zone(s) found: {', '.join(unknown_zones[:8])}")
    for idx, raw in df.skills.items():
        parsed = parse_skill_string(raw)
        if raw is not None and str(raw).strip() and not parsed:
            warnings.append(f"Resource row {idx + 2}: no valid governed skill entries were found.")
            if len(warnings) >= 12:
                break
    for col, lo, hi in [("delivery_rating", 0, 5), ("years_experience", 0, 60)]:
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce")
            if vals.isna().any():
                warnings.append(f"Column '{col}' contains missing/non-numeric values.")
            if ((vals.dropna() < lo) | (vals.dropna() > hi)).any():
                errors.append(f"Column '{col}' contains values outside {lo} to {hi}.")
    return ValidationReport(not errors, errors, warnings)



def validate_request(request: dict) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    required = ["start_date", "end_date", "role_mix"]
    if any(k not in request for k in required):
        return ValidationReport(False, ["The staffing request is incomplete."], warnings)
    try:
        start = pd.Timestamp(request["start_date"]).date()
        end = pd.Timestamp(request["end_date"]).date()
        if end < start:
            errors.append("End date cannot be before start date.")
        elif (end - start).days > 730:
            errors.append("Request duration cannot exceed two years.")
    except Exception:
        errors.append("Start and end dates must be valid dates.")

    role_mix = request.get("role_mix") or []
    if not isinstance(role_mix, list) or not role_mix:
        errors.append("Add at least one role and headcount.")
    else:
        seen = set()
        for row in role_mix:
            designation = row.get("designation")
            try:
                headcount = int(row.get("headcount", 0))
            except (TypeError, ValueError):
                headcount = 0

            allocation_hours = pd.to_numeric(
                row.get("allocation_hours"),
                errors="coerce",
            )

            allocation_pct = pd.to_numeric(
                row.get("allocation_pct"),
                errors="coerce",
            )

            if pd.isna(allocation_hours):
                errors.append(
                    f"{designation}: weekly allocation hours are required."
                )
            elif not 0.25 <= float(allocation_hours) <= STANDARD_WEEK_HOURS:
                errors.append(
                    f"{designation}: weekly allocation must be between "
                    f"0.25 and {STANDARD_WEEK_HOURS:g} hours."
                )

            if pd.isna(allocation_pct):
                errors.append(
                    f"{designation}: allocation percentage is required."
                )
            elif not 1 <= float(allocation_pct) <= 100:
                errors.append(
                    f"{designation}: allocation percentage must be between 1% and 100%."
                )

            if (
                pd.notna(allocation_hours)
                and pd.notna(allocation_pct)
            ):
                expected_pct = (
                    float(allocation_hours)
                    / STANDARD_WEEK_HOURS
                    * 100
                )

                if abs(float(allocation_pct) - expected_pct) > 0.1:
                    errors.append(
                        f"{designation}: allocation hours and percentage are inconsistent."
                    )
            if designation not in DESIGNATIONS:
                errors.append(f"Unsupported designation: {designation}")
            elif int(row.get("grade", DESIGNATION_TO_GRADE[designation])) != DESIGNATION_TO_GRADE[designation]:
                errors.append(f"Grade code does not match designation: {designation}")
            if not 1 <= headcount <= 50:
                errors.append("Each role headcount must be between 1 and 50.")
            key = designation
            if key in seen:
                errors.append(f"Duplicate role row: {designation}")
            seen.add(key)
            for skill_group in ["mandatory_skills", "preferred_skills"]:
                values = row.get(skill_group, {}) or {}
                if not isinstance(values, dict):
                    errors.append(f"{designation} {skill_group} must be a skill-to-level mapping.")
                    continue
                for skill, level in values.items():
                    if skill not in SKILL_CATALOG:
                        errors.append(f"Unsupported skill for {designation}: {skill}")
                    if level not in PROFICIENCY.values():
                        errors.append(f"Invalid proficiency for {designation}: {skill}")
            role_overlap = set(row.get("mandatory_skills", {})) & set(row.get("preferred_skills", {}))
            if role_overlap:
                warnings.append(
                    f"{designation}: mandatory takes precedence for {', '.join(sorted(role_overlap))}."
                )
    # Work country is a resource attribute used for travel matching, not a normal
    # staffing-request filter. Time zone and geographic expertise are separate gates.
    for field, allowed, label in [
        ("languages", LANGUAGES, "language"),
        ("time_zones", TIME_ZONES, "time zone"),
        ("geographies", GEOGRAPHIES, "geographic expertise"),
        ("travel_requirement", TRAVEL_REQUIREMENTS, "travel requirement"),
    ]:
        values = request.get(field, []) or []
        if field == "travel_requirement":
            values = [values] if not isinstance(values, (list, tuple, set)) else values
        for val in values:
            if val not in allowed:
                errors.append(f"Unsupported {label}: {val}")

    client_location = str(request.get("client_location") or "").strip()
    client_country = str(request.get("client_country") or "").strip()
    if client_location:
        expected_country = CLIENT_LOCATION_TO_COUNTRY.get(client_location)
        if expected_country and client_country and client_country != expected_country:
            errors.append(
                f"Client country does not match client location: {client_location}"
            )
        if expected_country and not client_country:
            client_country = expected_country

    travel_requirement = str(request.get("travel_requirement") or "No").strip()
    if travel_requirement == "Yes" and not client_country:
        errors.append("Client country is required when travel requirement is Yes.")
    for team in request.get("allowed_teams", []) or []:
        if not str(team).strip():
            errors.append("Specific team cannot be blank.")
    for group in ["mandatory_skills", "preferred_skills"]:
        values = request.get(group, {}) or {}
        if not isinstance(values, dict):
            errors.append(f"{group} must be a skill-to-level mapping.")
            continue
        for skill, lvl in values.items():
            if skill not in SKILL_CATALOG:
                errors.append(f"Unsupported skill: {skill}")
            if lvl not in PROFICIENCY.values():
                errors.append(f"Invalid proficiency for {skill}.")
    overlap = set(request.get("mandatory_skills", {})) & set(request.get("preferred_skills", {}))
    if overlap:
        warnings.append(f"Skills cannot be both mandatory and preferred. Mandatory takes precedence: {', '.join(sorted(overlap))}")
    has_role_skills = any(
        row.get("mandatory_skills") or row.get("preferred_skills")
        for row in role_mix
    )
    if not has_role_skills and not request.get("mandatory_skills") and not request.get("preferred_skills"):
        warnings.append("No skills were selected; recommendations will be driven by capacity and domain.")
    # Work country is intentionally not validated as a staffing filter.
    # Geographic expertise and time zone are independent request dimensions.
    return ValidationReport(not errors, errors, warnings)
