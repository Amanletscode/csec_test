from __future__ import annotations

from typing import Iterable

import pandas as pd

from .config import STANDARD_WEEK_HOURS


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIRMED_STATUS = "Confirmed"

CAPACITY_COLUMNS = [
    "resource_id",
    "week_start",
    "standard_week_hours",
    "allocated_hours",
    "allocated_pct",
    "available_hours",
    "available_capacity_pct",
    "active_project_count",
    "is_overallocated",
]

# Compatibility columns expected by the existing matching/discovery logic.
CAPACITY_COMPAT_COLUMNS = [
    "resource_id",
    "week_start",
    "available_capacity_pct",
]


# ---------------------------------------------------------------------------
# Date / week helpers
# ---------------------------------------------------------------------------

def _to_timestamp(value) -> pd.Timestamp | pd.NaT:
    """Safely convert a value to a normalized pandas Timestamp."""
    if pd.isna(value):
        return pd.NaT

    timestamp = pd.to_datetime(value, errors="coerce")

    if pd.isna(timestamp):
        return pd.NaT

    return pd.Timestamp(timestamp).normalize()


def _monday(value) -> pd.Timestamp | pd.NaT:
    """Return the Monday containing the supplied date."""
    timestamp = _to_timestamp(value)

    if pd.isna(timestamp):
        return pd.NaT

    return timestamp - pd.Timedelta(days=timestamp.weekday())


def _week_end(week_start: pd.Timestamp) -> pd.Timestamp:
    """Return Friday for a Monday-based working week."""
    return week_start + pd.Timedelta(days=4)


def _week_starts(
    start_date,
    end_date,
) -> pd.DatetimeIndex:
    """
    Return all Monday week-start dates covering the requested date range.

    The returned weeks are Monday-Friday working weeks.
    """
    start = _monday(start_date)
    end = _monday(end_date)

    if pd.isna(start) or pd.isna(end) or start > end:
        return pd.DatetimeIndex([])

    return pd.date_range(
        start=start,
        end=end,
        freq="W-MON",
    )


# ---------------------------------------------------------------------------
# Allocation helpers
# ---------------------------------------------------------------------------

def _normalize_allocations(
    allocations: pd.DataFrame,
) -> pd.DataFrame:
    """
    Normalize the allocation register into the fields required for
    capacity calculation.

    Allocation Hours / Week is authoritative. Allocation % is retained
    as a derived/check field only.
    """
    if allocations is None:
        return pd.DataFrame(
            columns=[
                "Employee ID",
                "Opportunity Number",
                "Allocation Hours / Week",
                "Allocation Start Date",
                "Allocation End Date",
                "Status",
            ]
        )

    df = allocations.copy()

    required_columns = [
        "Employee ID",
        "Opportunity Number",
        "Allocation Hours / Week",
        "Allocation Start Date",
        "Allocation End Date",
        "Status",
    ]

    missing = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing:
        raise ValueError(
            "Allocations data is missing required columns: "
            + ", ".join(missing)
        )

    df["Employee ID"] = df["Employee ID"].astype("string").str.strip()

    df["Opportunity Number"] = (
        df["Opportunity Number"]
        .astype("string")
        .str.strip()
    )

    df["Status"] = (
        df["Status"]
        .astype("string")
        .str.strip()
    )

    df["Allocation Hours / Week"] = pd.to_numeric(
        df["Allocation Hours / Week"],
        errors="coerce",
    )

    df["Allocation Start Date"] = pd.to_datetime(
        df["Allocation Start Date"],
        errors="coerce",
    ).dt.normalize()

    df["Allocation End Date"] = pd.to_datetime(
        df["Allocation End Date"],
        errors="coerce",
    ).dt.normalize()

    # Only confirmed allocations consume current capacity.
    df = df.loc[
        df["Status"].str.casefold().eq(CONFIRMED_STATUS.casefold())
    ].copy()

    # Invalid allocation rows cannot safely consume capacity.
    df = df.loc[
        df["Employee ID"].notna()
        & df["Allocation Start Date"].notna()
        & df["Allocation End Date"].notna()
        & df["Allocation Hours / Week"].notna()
    ].copy()

    # Do not allow negative weekly allocation to increase availability.
    df["Allocation Hours / Week"] = df[
        "Allocation Hours / Week"
    ].clip(lower=0)

    # Ignore malformed reversed date ranges.
    df = df.loc[
        df["Allocation End Date"] >= df["Allocation Start Date"]
    ].copy()

    return df


def _allocation_overlaps_working_week(
    allocation_start: pd.Timestamp,
    allocation_end: pd.Timestamp,
    week_start: pd.Timestamp,
) -> bool:
    """
    Determine whether an allocation overlaps at least one working day
    Monday-Friday of the supplied week.

    Saturday/Sunday are deliberately excluded from the capacity window.
    """
    working_week_start = week_start
    working_week_end = _week_end(week_start)

    return (
        allocation_start <= working_week_end
        and allocation_end >= working_week_start
    )


# ---------------------------------------------------------------------------
# Capacity builder
# ---------------------------------------------------------------------------

def build_weekly_capacity(
    resources: pd.DataFrame,
    allocations: pd.DataFrame,
    start_date,
    end_date,
) -> pd.DataFrame:
    """
    Build the derived weekly capacity dataset.

    Business rules
    --------------
    1. Standard workweek is STANDARD_WEEK_HOURS (42.5 hours).
    2. Working days are Monday-Friday.
    3. Every resource receives a row for every requested week.
    4. Only Confirmed allocations consume current capacity.
    5. Allocation Hours / Week is authoritative.
    6. An allocation applies to a week when it overlaps at least one
       working day in that Monday-Friday week.
    7. Partial-week allocations are not prorated.
    8. Employees without allocations remain at 100% availability.
    9. Over-allocation is retained as a diagnostic flag.
    10. Available capacity percentage is capped to 0-100.
    """
    if resources is None:
        raise ValueError("Resources data cannot be None.")

    if "resource_id" not in resources.columns:
        raise ValueError(
            "Resources data must contain a 'resource_id' column."
        )

    weeks = _week_starts(start_date, end_date)

    if len(weeks) == 0:
        return pd.DataFrame(columns=CAPACITY_COLUMNS)

    # ------------------------------------------------------------------
    # Normalize resource IDs.
    # ------------------------------------------------------------------

    resource_df = resources.copy()

    resource_df["resource_id"] = (
        resource_df["resource_id"]
        .astype("string")
        .str.strip()
    )

    resource_df = resource_df.loc[
        resource_df["resource_id"].notna()
        & resource_df["resource_id"].ne("")
    ].copy()

    resource_ids = (
        resource_df["resource_id"]
        .drop_duplicates()
        .tolist()
    )

    # ------------------------------------------------------------------
    # Build complete resource x week grid.
    # ------------------------------------------------------------------

    if not resource_ids:
        return pd.DataFrame(columns=CAPACITY_COLUMNS)

    resource_grid = pd.MultiIndex.from_product(
        [
            resource_ids,
            weeks,
        ],
        names=["resource_id", "week_start"],
    ).to_frame(index=False)

    resource_grid["standard_week_hours"] = float(
        STANDARD_WEEK_HOURS
    )

    # ------------------------------------------------------------------
    # Normalize confirmed allocations.
    # ------------------------------------------------------------------

    allocation_df = _normalize_allocations(allocations)

    # Only allocations belonging to resources in the resource master
    # can affect the capacity grid.
    allocation_df = allocation_df.loc[
        allocation_df["Employee ID"].isin(resource_ids)
    ].copy()

    # ------------------------------------------------------------------
    # Calculate allocated hours for each resource/week.
    # ------------------------------------------------------------------

    if allocation_df.empty:
        resource_grid["allocated_hours"] = 0.0
        resource_grid["active_project_count"] = 0

    else:
        rows: list[dict] = []

        allocation_rows = allocation_df[
            [
                "Employee ID",
                "Opportunity Number",
                "Allocation Hours / Week",
                "Allocation Start Date",
                "Allocation End Date",
            ]
        ].itertuples(
            index=False,
            name=None,
        )

        for (
            employee_id,
            opportunity_number,
            allocation_hours,
            allocation_start,
            allocation_end,
        ) in allocation_rows:

            allocation_hours = float(allocation_hours)

            for week_start in weeks:
                if _allocation_overlaps_working_week(
                    allocation_start,
                    allocation_end,
                    week_start,
                ):
                    rows.append(
                        {
                            "resource_id": employee_id,
                            "week_start": week_start,
                            "allocated_hours": allocation_hours,
                            "opportunity_number": opportunity_number,
                        }
                    )

        if rows:
            overlapping_allocations = pd.DataFrame(rows)

            weekly_allocations = (
                overlapping_allocations
                .groupby(
                    ["resource_id", "week_start"],
                    as_index=False,
                )
                .agg(
                    allocated_hours=(
                        "allocated_hours",
                        "sum",
                    ),
                    active_project_count=(
                        "opportunity_number",
                        "nunique",
                    ),
                )
            )

            resource_grid = resource_grid.merge(
                weekly_allocations,
                on=["resource_id", "week_start"],
                how="left",
            )

            resource_grid["allocated_hours"] = (
                resource_grid["allocated_hours"]
                .fillna(0.0)
            )

            resource_grid["active_project_count"] = (
                resource_grid["active_project_count"]
                .fillna(0)
                .astype(int)
            )

        else:
            resource_grid["allocated_hours"] = 0.0
            resource_grid["active_project_count"] = 0

    # ------------------------------------------------------------------
    # Calculate capacity.
    # ------------------------------------------------------------------

    resource_grid["allocated_pct"] = (
        resource_grid["allocated_hours"]
        / resource_grid["standard_week_hours"]
        * 100.0
    )

    resource_grid["available_hours"] = (
        resource_grid["standard_week_hours"]
        - resource_grid["allocated_hours"]
    )

    resource_grid["is_overallocated"] = (
        resource_grid["allocated_hours"]
        > resource_grid["standard_week_hours"]
    )

    resource_grid["available_capacity_pct"] = (
        resource_grid["available_hours"]
        / resource_grid["standard_week_hours"]
        * 100.0
    ).clip(
        lower=0.0,
        upper=100.0,
    )

    # ------------------------------------------------------------------
    # Final normalization.
    # ------------------------------------------------------------------

    resource_grid["week_start"] = pd.to_datetime(
        resource_grid["week_start"]
    ).dt.normalize()

    resource_grid = resource_grid[
        CAPACITY_COLUMNS
    ].sort_values(
        ["resource_id", "week_start"],
        kind="stable",
    ).reset_index(drop=True)

    return resource_grid


# ---------------------------------------------------------------------------
# Compatibility helper
# ---------------------------------------------------------------------------

def capacity_for_matching(
    capacity: pd.DataFrame,
) -> pd.DataFrame:
    """
    Return the minimal capacity schema expected by the existing
    matching/discovery engine.

    The full derived capacity dataset should be retained by the
    application for Capacity & Risk and diagnostics.
    """
    missing = [
        column
        for column in CAPACITY_COMPAT_COLUMNS
        if column not in capacity.columns
    ]

    if missing:
        raise ValueError(
            "Capacity data is missing required matching columns: "
            + ", ".join(missing)
        )

    return capacity[
        CAPACITY_COMPAT_COLUMNS
    ].copy()


__all__ = [
    "CAPACITY_COLUMNS",
    "CAPACITY_COMPAT_COLUMNS",
    "CONFIRMED_STATUS",
    "build_weekly_capacity",
    "capacity_for_matching",
]