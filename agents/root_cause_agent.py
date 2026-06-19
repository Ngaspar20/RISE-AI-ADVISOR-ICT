"""
root_cause_agent.py
───────────────────
WORKFLOW 3: Root Cause Analysis — Linkage Gaps

Answers: "What's driving poor linkage in specific districts/facilities?"

Approach:
  1. Stratify linkage gaps by contact type, age group, counselor experience
  2. Compare top vs bottom performers
  3. Send findings to Claude for causal narrative
"""

import pandas as pd
import numpy as np
import logging
from typing import Optional

from agents.base_agent import BaseAgent, AgentResult, RISE_CONTEXT
from tools import compute_metrics as cm
from tools import claude_client

logger = logging.getLogger(__name__)

ROOT_CAUSE_SYSTEM_PROMPT = f"""{RISE_CONTEXT}

You are the ROOT CAUSE ANALYSIS AGENT.

Your job:
1. Analyse the linkage gap data provided
2. Identify the primary driver(s) of poor linkage
3. Compare what top performers do differently
4. Generate a focused, actionable root cause report

Output format:

## ROOT CAUSE ANALYSIS: [District/Facility name]

### The Gap
[1-2 sentences: what is the overall linkage gap and how significant is it?]

### Primary Driver(s)
[The 1-2 most important factors explaining the gap. Be specific:]
- Is it a consent problem? (eligible contacts not consenting to be tested)
- Is it a testing completion problem? (consented contacts not tested)
- Is it a post-positive linkage problem? (HIV+ contacts not linked to care)
- Is it concentrated in a specific contact type (children, partners)?
- Is it concentrated in specific counselors?

### Evidence
[3-5 data points that support your conclusion. Use specific percentages.]

### What Top Performers Are Doing Differently
[1-3 concrete observations comparing best vs worst performers.]

### Recommended Actions
1. [Most impactful action, specific to the root cause]
2. [Secondary action]
3. [Optional monitoring/follow-up]

Rules:
- Base conclusions ONLY on the data provided
- Do not invent causation not supported by the data
- If data is insufficient to conclude, say so explicitly
- Keep the report to 1 page equivalent
"""

COUNSELOR_RCA_SYSTEM_PROMPT = f"""{RISE_CONTEXT}

You are the ROOT CAUSE ANALYSIS AGENT performing a COUNSELOR-LEVEL deep dive.

Analyse the specific counselor's performance data and generate a concise coaching brief:

## COUNSELOR PERFORMANCE BRIEF: [Counselor Name] at [Facility]

### Performance Summary
[3-4 bullet points with key metrics vs facility median]

### Root Cause Assessment
[What specifically is driving this counselor's underperformance?
Is it consent? Testing completion? Linkage after positive? Specific contact types?]

### Coaching Priorities
1. [Most important skill/protocol gap to address]
2. [Secondary gap]

### Suggested Coaching Approach
[Specific protocol, script, or technique to address the gap. Practical and concrete.]

Keep it to 1 page. Be direct — this is for a field supervisor preparing a coaching visit.
"""


class RootCauseAgent(BaseAgent):
    """Identifies drivers of linkage gaps at district, facility, or counselor level."""

    def __init__(self):
        super().__init__("RootCauseAgent")

    def run(
        self,
        df: pd.DataFrame,
        province: Optional[str] = None,
        district: Optional[str] = None,
        facility: Optional[str] = None,
        counselor: Optional[str] = None,
    ) -> AgentResult:
        """
        Run root cause analysis.

        If counselor is specified → counselor-level deep dive
        If facility is specified → facility-level analysis
        Else → district or programme-wide analysis
        """
        df_filtered = self._filter_df(df, province=province, district=district, facility=facility)
        if counselor:
            df_filtered = df_filtered[df_filtered["counselor"] == counselor]

        if len(df_filtered) == 0:
            return AgentResult(
                agent_name=self.name, success=False,
                narrative="No data for selected filters.", error="Empty dataset"
            )

        self.logger.info(
            f"Running RootCauseAgent: province={province} district={district} "
            f"facility={facility} counselor={counselor} | n={len(df_filtered):,}"
        )

        # ── Compute stratified breakdowns ──────────────────────────────────────
        by_contact_type = cm.stratify_by_contact_type(df_filtered)
        by_age_group = cm.stratify_by_age_group(df_filtered)
        counselor_metrics = cm.compute_counselor_metrics(df_filtered)

        # Compute linkage gap breakdown
        pipeline = _compute_linkage_pipeline(df_filtered)

        # Top vs bottom performers (if multiple counselors)
        top_performers, bottom_performers = _split_performers(counselor_metrics)

        # Build data prompt
        scope_label = counselor or facility or district or province or "Programme"
        is_counselor_rca = bool(counselor)

        data_prompt = _build_rca_prompt(
            scope_label, df_filtered, pipeline, by_contact_type,
            by_age_group, counselor_metrics, top_performers, bottom_performers,
            is_counselor_rca
        )

        system_prompt = COUNSELOR_RCA_SYSTEM_PROMPT if is_counselor_rca else ROOT_CAUSE_SYSTEM_PROMPT

        # ── Generate narrative ─────────────────────────────────────────────────
        narrative = ""
        if claude_client.is_configured():
            try:
                narrative = claude_client.call(
                    system_prompt=system_prompt,
                    user_prompt=data_prompt,
                    temperature=0.1,
                    max_tokens=2048,
                )
            except Exception as e:
                self.logger.error(f"Claude call failed: {e}")
                narrative = _fallback_rca(scope_label, pipeline, by_contact_type)
        else:
            narrative = _fallback_rca(scope_label, pipeline, by_contact_type)

        return AgentResult(
            agent_name=self.name,
            success=True,
            narrative=narrative,
            data={
                "pipeline": pipeline,
                "by_contact_type": by_contact_type,
                "by_age_group": by_age_group,
                "counselor_metrics": counselor_metrics,
                "top_performers": top_performers,
                "bottom_performers": bottom_performers,
                "scope": scope_label,
            },
        )


# ─── Analytics helpers ────────────────────────────────────────────────────────

def _compute_linkage_pipeline(df: pd.DataFrame) -> dict:
    """Decompose the linkage gap into its component steps."""
    n_total = len(df)
    n_eligible = df["eligible_bool"].sum()
    n_consented = df["consented"].sum()
    n_tested = df["was_tested"].sum()
    n_positive = df["is_positive"].sum()
    positives = df[df["is_positive"]]
    n_linked = positives["is_linked"].sum() if len(positives) > 0 else 0

    return {
        "n_total": int(n_total),
        "n_eligible": int(n_eligible),
        "eligible_rate": cm.safe_rate(n_eligible, n_total),
        "n_consented": int(n_consented),
        "consent_rate": cm.safe_rate(n_consented, n_eligible),
        "n_tested": int(n_tested),
        "testing_completion": cm.safe_rate(n_tested, n_consented),
        "n_positive": int(n_positive),
        "test_positivity": cm.safe_rate(n_positive, n_tested),
        "n_linked": int(n_linked),
        "linkage_rate": cm.safe_rate(n_linked, n_positive),
        "n_unlinked": int(n_positive - n_linked) if n_positive > 0 else 0,
    }


def _split_performers(counselor_metrics: pd.DataFrame):
    """Split counselors into top and bottom quartile by linkage rate."""
    df = counselor_metrics[counselor_metrics["n_contacts"] >= 5].copy()
    if len(df) < 4:
        return df, df

    q75 = df["linkage_rate"].quantile(0.75)
    q25 = df["linkage_rate"].quantile(0.25)

    top = df[df["linkage_rate"] >= q75][
        ["counselor", "facility", "n_contacts", "linkage_rate", "consent_rate",
         "testing_completion", "contact_yield"]
    ].sort_values("linkage_rate", ascending=False)

    bottom = df[df["linkage_rate"] <= q25][
        ["counselor", "facility", "n_contacts", "linkage_rate", "consent_rate",
         "testing_completion", "contact_yield"]
    ].sort_values("linkage_rate")

    return top, bottom


def _build_rca_prompt(
    scope: str, df: pd.DataFrame, pipeline: dict,
    by_type: pd.DataFrame, by_age: pd.DataFrame,
    counselor_metrics: pd.DataFrame,
    top: pd.DataFrame, bottom: pd.DataFrame,
    is_counselor_rca: bool
) -> str:

    pipeline_block = f"""
  Contacts enrolled: {pipeline['n_total']:,}
  Eligible for testing: {pipeline['n_eligible']:,} ({cm.format_pct(pipeline['eligible_rate'])})
  Consented to test: {pipeline['n_consented']:,} ({cm.format_pct(pipeline['consent_rate'])} of eligible)
  Actually tested: {pipeline['n_tested']:,} ({cm.format_pct(pipeline['testing_completion'])} of consented)
  HIV Positive: {pipeline['n_positive']:,} ({cm.format_pct(pipeline['test_positivity'])} positivity)
  Linked to care: {pipeline['n_linked']:,} ({cm.format_pct(pipeline['linkage_rate'])} of HIV+)
  NOT linked: {pipeline['n_unlinked']:,} — these are the gap cases"""

    type_block = "\n".join([
        f"  {r['contact_type']}: n={int(r['n_contacts'])} | "
        f"Consent={cm.format_pct(r.get('consent_rate', float('nan')))} | "
        f"Positivity={cm.format_pct(r.get('test_positivity', float('nan')))} | "
        f"Linkage={cm.format_pct(r.get('linkage_rate', float('nan')))}"
        for _, r in by_type.iterrows()
    ]) or "  No data"

    age_block = "\n".join([
        f"  {r['age_group']}: n={int(r['n_contacts'])} | "
        f"Linkage={cm.format_pct(r.get('linkage_rate', float('nan')))} | "
        f"Consent={cm.format_pct(r.get('consent_rate', float('nan')))}"
        for _, r in by_age.iterrows()
    ]) or "  No data"

    top_block = top.to_string(index=False) if not top.empty else "  Insufficient data"
    bottom_block = bottom.to_string(index=False) if not bottom.empty else "  Insufficient data"

    n_counselors = len(counselor_metrics)
    flag_summary = ""
    if not is_counselor_rca and n_counselors > 0 and "flag_any" in counselor_metrics.columns:
        flagged = counselor_metrics[counselor_metrics["flag_any"] == True] if "flag_any" in counselor_metrics.columns else pd.DataFrame()
        flag_summary = f"  {len(flagged)} of {n_counselors} counselors flagged below median"

    return f"""
ROOT CAUSE ANALYSIS REQUEST
Scope: {scope}
Total contacts in scope: {pipeline['n_total']:,}
{flag_summary}

═══ LINKAGE PIPELINE BREAKDOWN ═══
(Where in the cascade is the gap occurring?)
{pipeline_block}

═══ BREAKDOWN BY CONTACT TYPE ═══
{type_block}

═══ BREAKDOWN BY AGE GROUP ═══
{age_block}

═══ TOP PERFORMERS (top 25% by linkage) ═══
{top_block}

═══ BOTTOM PERFORMERS (bottom 25% by linkage) ═══
{bottom_block}

Please identify the PRIMARY driver of the linkage gap and recommend targeted actions.
"""


def _fallback_rca(scope: str, pipeline: dict, by_type: pd.DataFrame) -> str:
    lines = [f"## Root Cause Analysis: {scope}\n\n"]
    lines.append("### Linkage Pipeline\n")
    lines.append(f"- Consent rate: {cm.format_pct(pipeline['consent_rate'])}\n")
    lines.append(f"- Testing completion: {cm.format_pct(pipeline['testing_completion'])}\n")
    lines.append(f"- Linkage rate (HIV+): {cm.format_pct(pipeline['linkage_rate'])}\n")
    lines.append(f"- Unlinked positives: {pipeline['n_unlinked']}\n\n")

    if len(by_type) > 0:
        lines.append("### By Contact Type\n")
        for _, r in by_type.iterrows():
            lines.append(
                f"- {r['contact_type']}: "
                f"Linkage {cm.format_pct(r.get('linkage_rate', float('nan')))}, "
                f"n={int(r['n_contacts'])}\n"
            )

    lines.append("\n*Configure ANTHROPIC_API_KEY for AI-generated root cause narratives.*")
    return "".join(lines)
