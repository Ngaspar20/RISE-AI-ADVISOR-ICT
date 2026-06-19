"""
data_quality.py
───────────────
Runs structured quality checks on the loaded ICT line-list DataFrame.
Returns a DataQualityReport object consumed by the UI and agents.

Checks performed:
  1. Missing critical fields
  2. Outlier detection (activity spikes)
  3. Date inconsistencies
  4. Duplicate contacts
  5. Implausible values
  6. Linkage completeness for HIV+ contacts
"""

import pandas as pd
import numpy as np
import logging
from dataclasses import dataclass, field
from typing import List, Dict

logger = logging.getLogger(__name__)


@dataclass
class QualityIssue:
    severity: str           # "critical" | "warning" | "info"
    check: str              # name of the check that raised it
    description: str        # human-readable message
    affected_rows: int      # number of affected records
    affected_pct: float     # % of total records
    examples: List[str] = field(default_factory=list)  # example counselor/facility


@dataclass
class DataQualityReport:
    total_rows: int
    issues: List[QualityIssue] = field(default_factory=list)
    passed: bool = True     # False if any critical issues found

    @property
    def critical_issues(self) -> List[QualityIssue]:
        return [i for i in self.issues if i.severity == "critical"]

    @property
    def warnings(self) -> List[QualityIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def score(self) -> float:
        """0–100 quality score."""
        critical_weight = sum(i.affected_pct for i in self.critical_issues)
        warning_weight = sum(i.affected_pct * 0.3 for i in self.warnings)
        return max(0, 100 - critical_weight - warning_weight)

    def to_dict(self) -> Dict:
        return {
            "total_rows": self.total_rows,
            "passed": self.passed,
            "score": round(self.score, 1),
            "issues": [
                {
                    "severity": i.severity,
                    "check": i.check,
                    "description": i.description,
                    "affected_rows": i.affected_rows,
                    "affected_pct": round(i.affected_pct, 1),
                    "examples": i.examples,
                }
                for i in self.issues
            ],
        }


# ─── Public API ───────────────────────────────────────────────────────────────

def run_quality_checks(df: pd.DataFrame, alert_threshold_pct: float = 20.0) -> DataQualityReport:
    """
    Run all quality checks on the loaded DataFrame.

    Parameters
    ----------
    df               : normalised DataFrame from data_loader
    alert_threshold_pct : if critical issues affect >this% of records, mark as failed

    Returns
    -------
    DataQualityReport
    """
    report = DataQualityReport(total_rows=len(df))
    n = len(df)

    # Run all checks
    _check_missing_critical(df, report, n)
    _check_activity_outliers(df, report, n)
    _check_date_inconsistencies(df, report, n)
    _check_duplicates(df, report, n)
    _check_implausible_values(df, report, n)
    _check_linkage_completeness(df, report, n)
    _check_missing_counselor(df, report, n)

    # Mark as failed if critical issues exceed threshold
    total_critical_pct = sum(i.affected_pct for i in report.critical_issues)
    if total_critical_pct > alert_threshold_pct:
        report.passed = False
        logger.warning(
            f"Data quality FAILED: {total_critical_pct:.1f}% of records affected by critical issues."
        )

    logger.info(
        f"Quality check complete. Score: {report.score:.1f}/100 | "
        f"Critical: {len(report.critical_issues)} | Warnings: {len(report.warnings)}"
    )
    return report


# ─── Individual checks ────────────────────────────────────────────────────────

def _check_missing_critical(df: pd.DataFrame, report: DataQualityReport, n: int) -> None:
    """Check for missing values in fields required for metric calculation."""
    critical_cols = {
        "counselor": "Counselor name",
        "facility": "Facility (US)",
        "district": "District",
        "test_result": "HIV test result",
        "consented": "Contact consent",
    }
    for col, label in critical_cols.items():
        if col not in df.columns:
            continue
        missing = df[col].isna().sum()
        if missing > 0:
            report.issues.append(QualityIssue(
                severity="critical" if col in ("counselor", "test_result") else "warning",
                check="missing_critical_fields",
                description=f"{label}: {missing:,} records missing ({missing/n*100:.1f}%)",
                affected_rows=int(missing),
                affected_pct=missing / n * 100,
                examples=_sample_values(df[df[col].isna()], "facility", 3),
            ))


def _check_activity_outliers(df: pd.DataFrame, report: DataQualityReport, n: int) -> None:
    """Flag counselors with implausibly high contact counts (>5× median)."""
    if "counselor" not in df.columns or "index_case_id" not in df.columns:
        return

    # Contacts per counselor per week
    if "week" in df.columns:
        weekly = df.groupby(["counselor", "week"]).size()
        median_weekly = weekly.median()
        outlier_threshold = max(median_weekly * 5, 50)
        outliers = weekly[weekly > outlier_threshold]
        if not outliers.empty:
            examples = [f"{c} (week {w}: {v} contacts)" for (c, w), v in outliers.items()][:3]
            report.issues.append(QualityIssue(
                severity="warning",
                check="activity_outliers",
                description=f"{len(outliers)} counselor-week combinations have unusually high contact counts (>{outlier_threshold:.0f})",
                affected_rows=int(outliers.sum()),
                affected_pct=outliers.sum() / n * 100,
                examples=examples,
            ))


def _check_date_inconsistencies(df: pd.DataFrame, report: DataQualityReport, n: int) -> None:
    """Flag records where test date is before elicitation date."""
    if "elicitation_date" not in df.columns or "test_date" not in df.columns:
        return

    bad = df[
        df["elicitation_date"].notna() &
        df["test_date"].notna() &
        (df["test_date"] < df["elicitation_date"])
    ]
    if len(bad) > 0:
        report.issues.append(QualityIssue(
            severity="warning",
            check="date_inconsistency",
            description=f"{len(bad):,} records: test date is BEFORE elicitation date",
            affected_rows=len(bad),
            affected_pct=len(bad) / n * 100,
            examples=_sample_values(bad, "counselor", 3),
        ))

    # Also check consultation before test
    if "consultation_date" in df.columns:
        bad2 = df[
            df["consultation_date"].notna() &
            df["test_date"].notna() &
            (df["consultation_date"] < df["test_date"])
        ]
        if len(bad2) > 0:
            report.issues.append(QualityIssue(
                severity="warning",
                check="date_inconsistency",
                description=f"{len(bad2):,} records: consultation date is BEFORE test date",
                affected_rows=len(bad2),
                affected_pct=len(bad2) / n * 100,
                examples=_sample_values(bad2, "counselor", 3),
            ))


def _check_duplicates(df: pd.DataFrame, report: DataQualityReport, n: int) -> None:
    """Flag potential duplicate contact records."""
    dup_cols = ["index_case_id", "contact_type", "contact_sex", "contact_age", "test_date"]
    dup_cols = [c for c in dup_cols if c in df.columns]
    if len(dup_cols) < 3:
        return

    dups = df.duplicated(subset=dup_cols, keep=False)
    n_dups = dups.sum()
    if n_dups > 0:
        report.issues.append(QualityIssue(
            severity="warning",
            check="duplicates",
            description=f"{n_dups:,} records appear to be duplicates (same index case + contact attributes + date)",
            affected_rows=int(n_dups),
            affected_pct=n_dups / n * 100,
            examples=_sample_values(df[dups], "facility", 3),
        ))


def _check_implausible_values(df: pd.DataFrame, report: DataQualityReport, n: int) -> None:
    """Flag biologically implausible values."""
    if "contact_age" in df.columns:
        age = pd.to_numeric(df["contact_age"], errors="coerce")
        bad_age = ((age > 120) | (age < 0)).sum()
        if bad_age > 0:
            report.issues.append(QualityIssue(
                severity="warning",
                check="implausible_age",
                description=f"{bad_age:,} records have implausible contact age (>120 or <0)",
                affected_rows=int(bad_age),
                affected_pct=bad_age / n * 100,
            ))

    # Pregnant male contacts
    if "pregnant_lactating" in df.columns and "contact_sex" in df.columns:
        preg_male = df[
            (df["pregnant_lactating"] == "Sim") &
            (df["contact_sex"] == "Masculino")
        ]
        if len(preg_male) > 0:
            report.issues.append(QualityIssue(
                severity="warning",
                check="implausible_pregnancy",
                description=f"{len(preg_male):,} records show male contacts marked as pregnant/lactating",
                affected_rows=len(preg_male),
                affected_pct=len(preg_male) / n * 100,
                examples=_sample_values(preg_male, "facility", 3),
            ))


def _check_linkage_completeness(df: pd.DataFrame, report: DataQualityReport, n: int) -> None:
    """Check that HIV+ contacts have linkage status recorded."""
    if "is_positive" not in df.columns or "linkage" not in df.columns:
        return

    positives = df[df["is_positive"]]
    if len(positives) == 0:
        return

    no_linkage = positives[positives["linkage"].isna()]
    if len(no_linkage) > 0:
        report.issues.append(QualityIssue(
            severity="critical",
            check="linkage_completeness",
            description=(
                f"{len(no_linkage):,} of {len(positives):,} HIV+ contacts "
                f"({len(no_linkage)/len(positives)*100:.1f}%) have NO linkage status recorded"
            ),
            affected_rows=len(no_linkage),
            affected_pct=len(no_linkage) / n * 100,
            examples=_sample_values(no_linkage, "counselor", 3),
        ))


def _check_missing_counselor(df: pd.DataFrame, report: DataQualityReport, n: int) -> None:
    """Check for contacts with no counselor name (cannot be attributed)."""
    if "counselor" not in df.columns:
        return
    no_counselor = df[df["counselor"].isna()]
    if len(no_counselor) > 0:
        report.issues.append(QualityIssue(
            severity="critical",
            check="missing_counselor",
            description=f"{len(no_counselor):,} contacts have no counselor name — cannot attribute performance",
            affected_rows=len(no_counselor),
            affected_pct=len(no_counselor) / n * 100,
            examples=_sample_values(no_counselor, "facility", 3),
        ))


# ─── Utility ──────────────────────────────────────────────────────────────────

def _sample_values(df: pd.DataFrame, col: str, n: int) -> List[str]:
    """Return up to n unique non-null values from a column as strings."""
    if col not in df.columns:
        return []
    return df[col].dropna().unique()[:n].tolist()
