from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import (
    DEFAULT_WEIGHTS,
    DESIGNATION_TO_GRADE,
    STANDARD_WEEK_HOURS,
)

from .validation import parse_skill_string, split_pipe


@dataclass
class MatchResult:
    table: pd.DataFrame
    diagnostics: dict


def date_range_weeks(start, end) -> pd.DatetimeIndex:
    start_date = pd.Timestamp(start).normalize()
    end_date = pd.Timestamp(end).normalize()
    first_monday = start_date - pd.Timedelta(days=start_date.weekday())
    last_monday = end_date - pd.Timedelta(days=end_date.weekday())
    return pd.date_range(first_monday, last_monday, freq="7D")


def _prepare_capacity(capacity: pd.DataFrame | None) -> pd.DataFrame:
    columns = ["resource_id", "week_start", "available_capacity_pct"]
    if capacity is None or capacity.empty:
        return pd.DataFrame(columns=columns)
    prepared = capacity.copy()
    prepared["resource_id"] = prepared["resource_id"].astype(str)
    prepared["week_start"] = pd.to_datetime(prepared["week_start"], errors="coerce").dt.normalize()
    prepared["available_capacity_pct"] = pd.to_numeric(
        prepared["available_capacity_pct"], errors="coerce"
    )
    return prepared[columns]


def candidate_capacity(
    capacity: pd.DataFrame,
    resource_id: str,
    start,
    end,
    allocation: float,
) -> pd.DataFrame:
    weeks = date_range_weeks(start, end)
    prepared = _prepare_capacity(capacity)
    person = (
        prepared[prepared.resource_id.eq(str(resource_id))]
        .drop_duplicates("week_start")
        .set_index("week_start")
        .reindex(weeks)
    )
    available = pd.to_numeric(person["available_capacity_pct"], errors="coerce").astype(float)
    person["available_capacity_pct"] = available
    person["data_missing"] = available.isna()
    person["required_pct"] = float(allocation)
    person["gap_pct"] = (
        person["required_pct"] - available.fillna(0.0)
    ).clip(0, 100)
    person["status"] = np.where(
        person["data_missing"],
        "Missing capacity data",
        np.where(
            person["available_capacity_pct"] >= float(allocation),
            "Available",
            "Below requirement",
        ),
    )
    return person.reset_index(names="week_start")


def _capacity_stats(window: pd.DataFrame, allocation: float) -> dict:
    available = pd.to_numeric(window["available_capacity_pct"], errors="coerce")
    valid = available.dropna()
    return {
        "minimum_available_pct": float(valid.min()) if not valid.empty else 0.0,
        "median_available_pct": float(valid.median()) if not valid.empty else 0.0,
        "missing_weeks": int(available.isna().sum()),
        "weeks_below_demand": int((valid < float(allocation)).sum()),
        "coverage_ratio": float((valid >= float(allocation)).mean()) if not valid.empty else 0.0,
    }


def normalize_weights(weights: dict | None = None) -> dict[str, float]:
    entered = DEFAULT_WEIGHTS | (weights or {})
    clean = {}
    for key in DEFAULT_WEIGHTS:
        try:
            clean[key] = max(0.0, float(entered[key]))
        except (TypeError, ValueError):
            clean[key] = DEFAULT_WEIGHTS[key]
    total = sum(clean.values())
    return {key: value / total for key, value in clean.items()} if total else DEFAULT_WEIGHTS.copy()


def _coverage_score(candidate: dict[str, int], required: dict[str, int], empty: float) -> float:
    if not required:
        return empty
    return float(
        np.mean(
            [
                min(candidate.get(skill, 0) / max(level, 1), 1.0) * 100
                for skill, level in required.items()
            ]
        )
    )


def _proficiency_score(
    candidate: dict[str, int],
    mandatory: dict[str, int],
    preferred: dict[str, int],
) -> float:
    requirements = preferred | mandatory
    if not requirements:
        return 50.0
    values = []
    for skill, requested_level in requirements.items():
        actual = candidate.get(skill, 0)
        threshold = min(actual / max(requested_level, 1), 1.0) * 80
        depth = max(actual - requested_level, 0) / max(4 - requested_level, 1) * 20
        values.append(min(threshold + depth, 100))
    return float(np.mean(values))


def _capacity_score(stats: dict, allocation: float) -> float:
    if stats["missing_weeks"] or stats["weeks_below_demand"]:
        return 0.0
    spare = max(100.0 - float(allocation), 1.0)
    headroom = max(stats["minimum_available_pct"] - float(allocation), 0.0)
    return 80.0 + 20.0 * min(headroom / spare, 1.0)


def _role_key(index: int, role: dict) -> str:
    return f"role-{index + 1}-{role['designation']}"


def run_matching(
    resources: pd.DataFrame,
    capacity: pd.DataFrame,
    request: dict,
    weights: dict | None = None,
) -> MatchResult:
    if resources is None or resources.empty:
        return MatchResult(
            pd.DataFrame(),
            {
                "resources_assessed": 0,
                "eligible": 0,
                "excluded": 0,
                "requested_slots": 0,
                "fillable_slots": 0,
                "zero_match": True,
            },
        )

    normalized_weights = normalize_weights(weights)
    prepared_capacity = _prepare_capacity(capacity)
    capacity_by_resource = {
        resource_id: rows for resource_id, rows in prepared_capacity.groupby("resource_id", sort=False)
    }
    weeks = date_range_weeks(request["start_date"], request["end_date"])
    rows: list[dict] = []
    exclusion_counts = {
        key: 0
        for key in [
            "team",
            "time_zone",
            "language",
            "geographic_expertise",
            "travel",
            "grade",
            "mandatory_skill",
            "mandatory_proficiency",
            "capacity_data",
            "capacity",
        ]
    }

    for role_index, role in enumerate(request.get("role_mix") or []):
        designation = role["designation"]
        requested_grade = DESIGNATION_TO_GRADE[designation]

        role_allocation_pct = float(
            role.get(
                "allocation_pct",
                request.get("allocation_pct", 50),
            )
        )
        role_key = _role_key(role_index, role)
        # A mixed team can need different capabilities at each level. Legacy
        # request-level skills remain a safe fallback for uploaded integrations.
        mandatory = role.get("mandatory_skills", request.get("mandatory_skills")) or {}
        preferred = role.get("preferred_skills", request.get("preferred_skills")) or {}
        for _, resource in resources.iterrows():
            resource_id = str(resource.get("resource_id", ""))
            skills = parse_skill_string(resource.get("skills"))
            missing_skills = [skill for skill in mandatory if skill not in skills]
            low_skills = [
                skill
                for skill, level in mandatory.items()
                if skill in skills and skills[skill] < level
            ]
            window = candidate_capacity(
                capacity_by_resource.get(resource_id, prepared_capacity.iloc[0:0]),
                resource_id,
                request["start_date"],
                request["end_date"],
                role_allocation_pct,
            )
            stats = _capacity_stats(
                window,
                role_allocation_pct,
            )
            resource_grade = pd.to_numeric(resource.get("grade"), errors="coerce")

            resource_geographies = split_pipe(resource.get("geography_expertise"))
            requested_geographies = set(request.get("geographies") or [])
            geography_pass = (
                not requested_geographies
                or bool(requested_geographies.intersection(resource_geographies))
            )

            travel_required = (
                str(request.get("travel_requirement") or "No").strip().casefold() == "yes"
            )
            client_country = str(request.get("client_country") or "").strip()
            resource_country = str(resource.get("location") or "").strip()
            travel_pass = (
                not travel_required
                or (
                    bool(client_country)
                    and bool(resource_country)
                    and resource_country.casefold() == client_country.casefold()
                )
            )

            gates = {
                "Specific team": not request.get("allowed_teams")
                or str(resource.get("team")) in request["allowed_teams"],
                "Time zone": not request.get("time_zones")
                or str(resource.get("time_zone")) in request["time_zones"],
                "Language": set(request.get("languages") or []).issubset(
                    split_pipe(resource.get("languages"))
                ),
                "Geographic expertise": geography_pass,
                "Travel": travel_pass,
                "Grade / designation": pd.notna(resource_grade)
                and int(resource_grade) == requested_grade
                and str(resource.get("role_title")) == designation,
                "Mandatory skill presence": not missing_skills,
                "Mandatory proficiency": not low_skills,
                "Capacity data": stats["missing_weeks"] == 0,
                "Weekly available capacity": stats["weeks_below_demand"] == 0,
            }
            reason_map = {
                "Specific team": "Team does not match",
                "Time zone": "Time zone does not match",
                "Language": "Required language is missing",
                "Geographic expertise": "Geographic expertise does not match",
                "Travel": "Work country does not match the client country required for travel",
                "Grade / designation": "Grade or designation does not match",
                "Mandatory skill presence": "Mandatory skill is missing",
                "Mandatory proficiency": "Mandatory proficiency is below requirement",
                "Capacity data": "Weekly capacity data is incomplete",
                "Weekly available capacity": "Available capacity is below the requested allocation",
            }
            reasons = [reason_map[name] for name, passed in gates.items() if not passed]
            count_keys = {
                "team": "Specific team",
                "time_zone": "Time zone",
                "language": "Language",
                "geographic_expertise": "Geographic expertise",
                "travel": "Travel",
                "grade": "Grade / designation",
                "mandatory_skill": "Mandatory skill presence",
                "mandatory_proficiency": "Mandatory proficiency",
                "capacity_data": "Capacity data",
                "capacity": "Weekly available capacity",
            }
            for count_key, gate_name in count_keys.items():
                if not gates[gate_name]:
                    exclusion_counts[count_key] += 1

            raw_scores = {
                "mandatory_skills": _coverage_score(skills, mandatory, 100.0),
                "preferred_skills": _coverage_score(skills, preferred, 50.0),
                "proficiency": _proficiency_score(skills, mandatory, preferred),
                "capacity": _capacity_score(
                    stats,
                    role_allocation_pct,
                ),
            }
            components = {
                name: score * normalized_weights[name]
                for name, score in raw_scores.items()
            }
            potential_score = float(sum(components.values()))
            eligible = not reasons
            rows.append(
                {
                    "role_key": role_key,
                    "requested_designation": designation,
                    "requested_allocation_hours": float(
                        role.get(
                            "allocation_hours",
                            role_allocation_pct / 100 * STANDARD_WEEK_HOURS,
                        )
                    ),
                    "requested_allocation_pct": role_allocation_pct,
                    "requested_grade": requested_grade,
                    "requested_headcount": int(role["headcount"]),
                    "requested_mandatory_skills": mandatory,
                    "requested_preferred_skills": preferred,
                    "resource_id": resource_id,
                    "resource_name": str(resource.get("resource_name", "")),
                    "team": str(resource.get("team", "")),
                    "grade": int(resource_grade) if pd.notna(resource_grade) else 0,
                    "role_title": str(resource.get("role_title", "")),
                    "location": str(resource.get("location", "")),
                    "work_city": str(resource.get("work_city", "")),
                    "time_zone": str(resource.get("time_zone", "")),
                    "languages": str(resource.get("languages", "")),
                    "status": "Eligible" if eligible else "Excluded",
                    "exclusion_reasons": reasons,
                    "gates": gates,
                    "total_score": round(potential_score if eligible else 0.0, 2),
                    "potential_score": round(potential_score, 2),
                    "score_components": {
                        name: round(value, 2) for name, value in components.items()
                    },
                    "minimum_available_pct": round(stats["minimum_available_pct"], 1),
                    "median_available_pct": round(stats["median_available_pct"], 1),
                    "weeks_below_demand": stats["weeks_below_demand"],
                    "missing_capacity_weeks": stats["missing_weeks"],
                    "missing_mandatory_skills": missing_skills,
                    "below_mandatory_skills": low_skills,
                    "missing_preferred_skills": [
                        skill for skill in preferred if skill not in skills
                    ],
                    "domains": str(resource.get("domains", "")),
                    "geography_expertise": str(resource.get("geography_expertise", "")),
                    "project_expertise": str(resource.get("project_expertise", "")),
                    "manager_name": str(resource.get("manager_name", "Not provided")),
                    "manager_email": str(resource.get("manager_email", "")),
                    "contact_email": str(resource.get("contact_email", "")),
                }
            )

    table = pd.DataFrame(rows)
    if table.empty:
        return MatchResult(table, {"resources_assessed": len(resources), "zero_match": True})

    table["rank"] = 0
    table["fit_percentile"] = 0.0
    fillable_slots = 0
    role_summary = []
    for role_key, role_rows in table.groupby("role_key", sort=False):
        eligible_rows = role_rows[role_rows.status.eq("Eligible")].sort_values(
            ["total_score", "minimum_available_pct", "resource_name"],
            ascending=[False, False, True],
        )
        if not eligible_rows.empty:
            table.loc[eligible_rows.index, "rank"] = range(1, len(eligible_rows) + 1)
            table.loc[eligible_rows.index, "fit_percentile"] = (
                100.0
                if len(eligible_rows) == 1
                else eligible_rows.total_score.rank(method="min", pct=True).mul(100).round(1)
            )
        requested = int(role_rows.iloc[0]["requested_headcount"])
        fillable_slots += min(requested, len(eligible_rows))
        role_summary.append(
            {
                "role_key": role_key,
                "designation": role_rows.iloc[0]["requested_designation"],
                "grade": int(role_rows.iloc[0]["requested_grade"]),
                "requested": requested,
                "eligible": len(eligible_rows),
            }
        )

    table = table.sort_values(
        ["role_key", "status", "rank", "resource_name"],
        ascending=[True, False, True, True],
    ).reset_index(drop=True)
    requested_slots = sum(int(role["headcount"]) for role in request.get("role_mix") or [])
    diagnostics = {
        "resources_assessed": len(resources),
        "candidate_role_assessments": len(table),
        "eligible": int(table.status.eq("Eligible").sum()),
        "excluded": int(table.status.eq("Excluded").sum()),
        "requested_slots": requested_slots,
        "fillable_slots": fillable_slots,
        "zero_match": fillable_slots == 0,
        "request_window_weeks": len(weeks),
        "gate_exclusion_counts": exclusion_counts,
        "roles": role_summary,
    }
    return MatchResult(table, diagnostics)


def build_team(result_table: pd.DataFrame) -> list[dict]:
    if result_table is None or result_table.empty:
        return []
    selected_ids: set[str] = set()
    team: list[dict] = []
    for role_key, role_rows in result_table.groupby("role_key", sort=False):
        requested = int(role_rows.iloc[0]["requested_headcount"])
        pool = role_rows[role_rows.status.eq("Eligible")].sort_values(
            ["rank", "total_score", "minimum_available_pct"],
            ascending=[True, False, False],
        )
        for slot in range(1, requested + 1):
            available = pool[~pool.resource_id.astype(str).isin(selected_ids)]
            if available.empty:
                team.append(
                    {
                        "role_key": role_key,
                        "designation": role_rows.iloc[0]["requested_designation"],
                        "slot": slot,
                        "status": "Unfilled",
                    }
                )
                continue
            candidate = available.iloc[0]
            selected_ids.add(str(candidate.resource_id))
            team.append(
                {
                    "role_key": role_key,
                    "designation": candidate.requested_designation,
                    "slot": slot,
                    "status": "Filled",
                    "resource_id": candidate.resource_id,
                    "resource_name": candidate.resource_name,
                    "team": candidate.team,
                    "location": candidate.location,
                    "fit_score": candidate.total_score,
                    "minimum_available_pct": candidate.minimum_available_pct,
                    "contact_email": candidate.contact_email,
                }
            )
    return team


def build_alternatives(
    result_table: pd.DataFrame,
    selected_id: str,
    role_key: str | None = None,
    limit: int = 3,
) -> list[dict]:
    if result_table is None or result_table.empty:
        return []
    pool = result_table[
        result_table.status.eq("Eligible")
        & result_table.resource_id.astype(str).ne(str(selected_id))
    ]
    if role_key:
        pool = pool[pool.role_key.eq(role_key)]
    return (
        pool.sort_values(["total_score", "minimum_available_pct"], ascending=[False, False])
        .head(limit)[
            [
                "resource_id",
                "resource_name",
                "team",
                "role_title",
                "grade",
                "location",
                "total_score",
                "minimum_available_pct",
            ]
        ]
        .to_dict("records")
    )


def build_near_matches(
    result_table: pd.DataFrame,
    role_key: str | None = None,
    limit: int = 5,
    max_failed_gates: int = 2,
) -> list[dict]:
    if result_table is None or result_table.empty:
        return []
    excluded = result_table[result_table.status.eq("Excluded")].copy()
    if role_key:
        excluded = excluded[excluded.role_key.eq(role_key)]
    excluded["failed_gate_count"] = excluded.exclusion_reasons.map(len)
    return (
        excluded[excluded.failed_gate_count.le(max_failed_gates)]
        .sort_values(
            ["failed_gate_count", "potential_score", "minimum_available_pct"],
            ascending=[True, False, False],
        )
        .head(limit)[
            [
                "role_key",
                "resource_id",
                "resource_name",
                "role_title",
                "grade",
                "team",
                "location",
                "potential_score",
                "minimum_available_pct",
                "failed_gate_count",
                "exclusion_reasons",
            ]
        ]
        .to_dict("records")
    )
