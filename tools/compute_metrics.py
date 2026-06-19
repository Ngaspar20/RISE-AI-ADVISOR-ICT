"""
compute_metrics.py
──────────────────
Core analytics engine for the RISE ICT programme.

Implements the two-level hierarchical benchmarking model:
  Level 1: Counselor vs. their facility median
  Level 2: Facility median vs. their district median

All metric functions return DataFrames with standardised columns
that agents and output generators consume directly.
"""

import pandas as pd
import numpy as np
import yaml
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
with open(_CONFIG_PATH, encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

THRESHOLDS = CONFIG["thresholds"]
MIN_RECORDS = THRESHOLDS["min_records_for_metrics"]
BELOW_FLAG_PCT = THRESHOLDS["below_median_flag_pct"]


# ─── Metric calculation at counselor level ────────────────────────────────────

def compute_counselor_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-counselor performance metrics.

    Returns
    -------
    DataFrame with one row per counselor, columns:
      counselor, facility, district, province,
      n_contacts, n_index_cases, contact_yield,
      n_eligible, n_consented, consent_rate,
      n_tested, testing_completion,
      n_positive, test_positivity,
      n_linked, linkage_rate,
      median_turnaround_days
    """
    rows = []
    for (counselor, facility, district, province), grp in df.groupby(
        ["counselor", "facility", "district", "province"], observed=True
    ):
        if counselor is None or pd.isna(counselor):
            continue

        n = len(grp)
        n_index = grp["index_case_id"].nunique() if "index_case_id" in grp.columns else np.nan

        # Consent rate: consented / eligible
        n_eligible = grp["eligible_bool"].sum()
        n_consented = grp["consented"].sum()
        consent_rate = safe_rate(n_consented, n_eligible)

        # Testing completion: tested / consented
        n_tested = grp["was_tested"].sum()
        testing_completion = safe_rate(n_tested, n_consented)

        # Test positivity: HIV+ / tested
        n_positive = grp["is_positive"].sum()
        test_positivity = safe_rate(n_positive, n_tested)

        # Linkage rate: linked / HIV+  (only among positives)
        positives = grp[grp["is_positive"]]
        n_positive_total = len(positives)
        n_linked = positives["is_linked"].sum()
        linkage_rate = safe_rate(n_linked, n_positive_total)

        # Contact yield: contacts per index case
        contact_yield = n / n_index if (n_index and n_index > 0) else np.nan

        # Turnaround
        median_tat = (
            grp["turnaround_days"].median()
            if "turnaround_days" in grp.columns
            else np.nan
        )

        rows.append({
            "counselor": counselor,
            "facility": facility,
            "district": district,
            "province": province,
            "n_contacts": n,
            "n_index_cases": n_index,
            "contact_yield": round(contact_yield, 2) if not np.isnan(contact_yield) else np.nan,
            "n_eligible": int(n_eligible),
            "n_consented": int(n_consented),
            "consent_rate": consent_rate,
            "n_tested": int(n_tested),
            "testing_completion": testing_completion,
            "n_positive": int(n_positive),
            "test_positivity": test_positivity,
            "n_positive_total": int(n_positive_total),
            "n_linked": int(n_linked),
            "linkage_rate": linkage_rate,
            "median_turnaround_days": round(median_tat, 1) if not np.isnan(median_tat) else np.nan,
        })

    return pd.DataFrame(rows)


def compute_facility_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-facility performance metrics (median of counselor metrics within facility).

    Returns one row per facility with the same metric columns + facility_median prefix.
    """
    counselor_df = compute_counselor_metrics(df)
    metric_cols = ["consent_rate", "testing_completion", "test_positivity", "linkage_rate",
                   "contact_yield", "median_turnaround_days"]

    rows = []
    for (facility, district, province), grp in counselor_df.groupby(
        ["facility", "district", "province"], observed=True
    ):
        # Only use counselors with enough data
        grp_filtered = grp[grp["n_contacts"] >= MIN_RECORDS]
        if len(grp_filtered) == 0:
            grp_filtered = grp  # fall back to all if everyone is below threshold

        row = {
            "facility": facility,
            "district": district,
            "province": province,
            "n_counselors": len(grp),
            "n_counselors_active": len(grp_filtered),
            "n_contacts_total": grp["n_contacts"].sum(),
        }
        for col in metric_cols:
            row[f"median_{col}"] = grp_filtered[col].median()
            row[f"min_{col}"] = grp_filtered[col].min()
            row[f"max_{col}"] = grp_filtered[col].max()

        rows.append(row)

    return pd.DataFrame(rows)


def compute_district_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-district performance metrics (median of facility medians within district).

    Returns one row per district.
    """
    facility_df = compute_facility_metrics(df)
    metric_cols = ["consent_rate", "testing_completion", "test_positivity", "linkage_rate",
                   "contact_yield", "median_turnaround_days"]

    rows = []
    for (district, province), grp in facility_df.groupby(["district", "province"], observed=True):
        row = {
            "district": district,
            "province": province,
            "n_facilities": len(grp),
            "n_contacts_total": grp["n_contacts_total"].sum(),
        }
        for col in metric_cols:
            src_col = f"median_{col}"
            if src_col in grp.columns:
                row[f"district_median_{col}"] = grp[src_col].median()
        rows.append(row)

    return pd.DataFrame(rows)


# ─── Benchmarking: flag counselors and facilities ─────────────────────────────

def flag_counselors(df: pd.DataFrame) -> pd.DataFrame:
    """
    Level 1 benchmarking: compare each counselor to their facility median.

    Returns counselor_metrics with added columns:
      facility_median_{metric}, pct_below_facility_{metric}, flag_{metric}
    """
    counselor_df = compute_counselor_metrics(df)
    facility_df = compute_facility_metrics(df)

    # Prioritise: volume (testing_completion, contact_yield), quality (test_positivity)
    # Linkage is tracked separately but NOT a flag driver
    metric_cols = ["testing_completion", "test_positivity", "contact_yield", "consent_rate"]

    # Join facility medians onto counselor rows
    facility_medians = facility_df[
        ["facility"] + [f"median_{c}" for c in metric_cols]
    ].rename(columns={f"median_{c}": f"facility_median_{c}" for c in metric_cols})

    result = counselor_df.merge(facility_medians, on="facility", how="left")

    # Compute % below facility median and set flags
    result["flag_any"] = False
    result["flags"] = ""
    result["severity"] = "green"

    for col in metric_cols:
        fac_col = f"facility_median_{col}"
        pct_col = f"pct_below_facility_{col}"
        flag_col = f"flag_{col}"

        result[pct_col] = (
            (result[fac_col] - result[col]) / result[fac_col].replace(0, np.nan) * 100
        ).round(1)

        result[flag_col] = (
            result[pct_col] >= BELOW_FLAG_PCT
        ) & (result["n_contacts"] >= MIN_RECORDS)

        # Accumulate flag labels
        flagged_mask = result[flag_col]
        result.loc[flagged_mask, "flags"] += f"{col} "
        result.loc[flagged_mask, "flag_any"] = True

    # RED = low testing completion or low positivity (core programme gaps)
    red_mask = result["flag_testing_completion"] | result["flag_test_positivity"]
    result.loc[red_mask & result["flag_any"], "severity"] = "red"
    result.loc[~red_mask & result["flag_any"], "severity"] = "yellow"

    result["flags"] = result["flags"].str.strip()
    return result.sort_values(["severity", "test_positivity"], ascending=[True, True])


def flag_facilities(df: pd.DataFrame) -> pd.DataFrame:
    """
    Level 2 benchmarking: compare each facility median to its district median.

    Returns facility_metrics with added columns:
      district_median_{metric}, pct_below_district_{metric}, flag_{metric}
    """
    facility_df = compute_facility_metrics(df)
    district_df = compute_district_metrics(df)

    # Prioritise: volume (testing_completion, contact_yield), quality (test_positivity)
    # Linkage is tracked separately but NOT a flag driver
    metric_cols = ["testing_completion", "test_positivity", "contact_yield", "consent_rate"]

    district_medians = district_df[
        ["district"] + [f"district_median_{c}" for c in metric_cols]
    ]

    result = facility_df.merge(district_medians, on="district", how="left")
    result["flag_any"] = False
    result["flags"] = ""
    result["severity"] = "green"

    for col in metric_cols:
        dist_col = f"district_median_{col}"
        fac_col = f"median_{col}"
        pct_col = f"pct_below_district_{col}"
        flag_col = f"flag_{col}"

        result[pct_col] = (
            (result[dist_col] - result[fac_col]) / result[dist_col].replace(0, np.nan) * 100
        ).round(1)

        result[flag_col] = (
            result[pct_col] >= BELOW_FLAG_PCT
        ) & (result["n_contacts_total"] >= MIN_RECORDS)

        flagged_mask = result[flag_col]
        result.loc[flagged_mask, "flags"] += f"{col} "
        result.loc[flagged_mask, "flag_any"] = True

    red_mask = result.get("flag_testing_completion", False) | result.get("flag_test_positivity", False)
    result.loc[red_mask & result["flag_any"], "severity"] = "red"
    result.loc[~red_mask & result["flag_any"], "severity"] = "yellow"

    result["flags"] = result["flags"].str.strip()
    return result.sort_values(["severity", "median_test_positivity"], ascending=[True, True])


# ─── Time series ──────────────────────────────────────────────────────────────

def compute_weekly_trends(df: pd.DataFrame, level: str = "district") -> pd.DataFrame:
    """
    Compute weekly metric trends at district, facility, or counselor level.

    Parameters
    ----------
    level : "district" | "facility" | "counselor"
    """
    if "week" not in df.columns or "test_date" not in df.columns:
        return pd.DataFrame()

    group_cols = {"district": ["district", "province", "week"],
                  "facility": ["facility", "district", "week"],
                  "counselor": ["counselor", "facility", "week"]}

    cols = group_cols.get(level, ["district", "week"])
    rows = []

    for keys, grp in df.groupby(cols, observed=True):
        key_dict = dict(zip(cols, keys if isinstance(keys, tuple) else [keys]))
        n_positive = grp["is_positive"].sum()
        n_tested = grp["was_tested"].sum()
        n_linked = grp[grp["is_positive"]]["is_linked"].sum()
        n_eligible = grp["eligible_bool"].sum()
        n_consented = grp["consented"].sum()

        key_dict.update({
            "n_contacts": len(grp),
            "n_tested": int(n_tested),
            "n_positive": int(n_positive),
            "n_linked": int(n_linked),
            "linkage_rate": safe_rate(n_linked, n_positive),
            "test_positivity": safe_rate(n_positive, n_tested),
            "consent_rate": safe_rate(n_consented, n_eligible),
        })
        rows.append(key_dict)

    result = pd.DataFrame(rows)
    if "week" in result.columns:
        result = result.sort_values("week")
    return result


# ─── Stratified analysis ──────────────────────────────────────────────────────

def stratify_by_contact_type(df: pd.DataFrame) -> pd.DataFrame:
    """Break down linkage rate and positivity by contact type."""
    rows = []
    for ctype, grp in df.groupby("contact_type", observed=True):
        n = len(grp)
        n_pos = grp["is_positive"].sum()
        n_linked = grp[grp["is_positive"]]["is_linked"].sum()
        n_consented = grp["consented"].sum()
        rows.append({
            "contact_type": ctype,
            "n_contacts": n,
            "n_positive": int(n_pos),
            "test_positivity": safe_rate(n_pos, grp["was_tested"].sum()),
            "linkage_rate": safe_rate(n_linked, n_pos),
            "consent_rate": safe_rate(n_consented, grp["eligible_bool"].sum()),
        })
    return pd.DataFrame(rows).sort_values("n_contacts", ascending=False)


def stratify_by_age_group(df: pd.DataFrame) -> pd.DataFrame:
    """Break down linkage rate by contact age group."""
    rows = []
    for age_grp, grp in df.groupby("age_group", observed=True):
        n_pos = grp["is_positive"].sum()
        n_linked = grp[grp["is_positive"]]["is_linked"].sum()
        rows.append({
            "age_group": str(age_grp),
            "n_contacts": len(grp),
            "n_positive": int(n_pos),
            "linkage_rate": safe_rate(n_linked, n_pos),
            "consent_rate": safe_rate(grp["consented"].sum(), grp["eligible_bool"].sum()),
        })
    return pd.DataFrame(rows)


# ─── Utility ──────────────────────────────────────────────────────────────────

def safe_rate(numerator, denominator) -> float:
    """Return percentage, or NaN if denominator is 0 or NaN."""
    try:
        if denominator == 0 or pd.isna(denominator):
            return np.nan
        return round(float(numerator) / float(denominator) * 100, 1)
    except (TypeError, ValueError):
        return np.nan


def format_pct(value: float, decimals: int = 1) -> str:
    """Format a percentage for display."""
    if pd.isna(value):
        return "N/A"
    return f"{value:.{decimals}f}%"


def traffic_light(value: float, median: float) -> str:
    """Return 🔴 / 🟡 / 🟢 based on % below median."""
    if pd.isna(value) or pd.isna(median) or median == 0:
        return "⚪"
    pct_below = (median - value) / median * 100
    if pct_below >= BELOW_FLAG_PCT:
        return "🔴"
    elif pct_below >= BELOW_FLAG_PCT * 0.5:
        return "🟡"
    return "🟢"
