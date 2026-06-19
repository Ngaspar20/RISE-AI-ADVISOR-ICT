"""
flagging_agent.py
─────────────────
WORKFLOW 1: Counselor & Facility Performance Flagging

Answers: "Which counselors and facilities need immediate technical assistance?"

Steps:
  1. Compute counselor metrics
  2. Apply Level 1 benchmarking (counselor vs facility median)
  3. Apply Level 2 benchmarking (facility vs district median)
  4. Send flagged data to Claude for narrative generation
  5. Return structured flags + narrative for supervisor briefs
"""

import pandas as pd
import numpy as np
import logging
from typing import Optional

from agents.base_agent import BaseAgent, AgentResult, RISE_CONTEXT
from tools import compute_metrics as cm
from tools import claude_client

logger = logging.getLogger(__name__)

FLAGGING_SYSTEM_PROMPT = f"""{RISE_CONTEXT}

És o AGENTE DE SINALIZAÇÃO DE DESEMPENHO do programa RISE ICT.

Foco principal: volume de testagem, positividade e positivos encontrados.
A linkagem NÃO é um indicador prioritário nesta análise.

Analisa os dados fornecidos e gera um briefing de supervisão em PORTUGUÊS.

## RESUMO DO PERÍODO
[1-2 frases: estado geral do distrito. Volume testado, positividade, tendências.]

## 🔴 PRIORIDADES CRÍTICAS
[Máximo 5 sinalizações, as mais graves primeiro. Para cada uma:]
[TIPO: UNIDADE ou CONSELHEIRO]
[Nome] em [US/Distrito]: [indicador] [X%] vs mediana [Y%]
→ Recomendação: [acção concreta, 1 frase]

## 🟡 SITUAÇÕES DE ATENÇÃO
[Conselheiros/unidades a monitorar. Máximo 3.]

## 💡 PONTOS POSITIVOS
[1-2 boas práticas a reforçar.]

Regras:
- Cita sempre nomes de conselheiros e unidades explicitamente
- Usa sempre números concretos (ex: "positividade 3% vs mediana 8%")
- Foca em: volume testado, positividade, positivos encontrados
- Não mencionar linkagem como prioridade
- Responde SEMPRE em Português
"""

class FlaggingAgent(BaseAgent):
    """Identifies counselors and facilities needing immediate technical assistance."""

    def __init__(self):
        super().__init__("FlaggingAgent")

    def run(
        self,
        df: pd.DataFrame,
        province: Optional[str] = None,
        district: Optional[str] = None,
        max_flags: int = 5,
    ) -> AgentResult:
        """
        Run performance flagging on the dataset.

        Parameters
        ----------
        df        : Full normalised ICT line-list
        province  : Filter to specific province (optional)
        district  : Filter to specific district (optional)
        max_flags : Maximum number of red flags to surface

        Returns
        -------
        AgentResult with:
          narrative       : Supervisor brief text (from Claude)
          data.counselor_flags : DataFrame of flagged counselors
          data.facility_flags  : DataFrame of flagged facilities
          data.counselor_metrics : Full counselor metrics table
          data.facility_metrics  : Full facility metrics table
          data.district_metrics  : District baseline metrics
        """
        df_filtered = self._filter_df(df, province=province, district=district)
        if len(df_filtered) == 0:
            return AgentResult(
                agent_name=self.name,
                success=False,
                narrative="No data found for the selected filters.",
                error="Empty dataset after filtering",
            )

        self.logger.info(
            f"Running FlaggingAgent on {len(df_filtered):,} records | "
            f"province={province} | district={district}"
        )

        # ── Step 1: Compute metrics ────────────────────────────────────────────
        counselor_metrics = cm.flag_counselors(df_filtered)
        facility_metrics = cm.flag_facilities(df_filtered)
        district_metrics = cm.compute_district_metrics(df_filtered)

        # ── Step 2: Extract red flags ──────────────────────────────────────────
        counselor_flags = counselor_metrics[
            counselor_metrics["flag_any"] & (counselor_metrics["n_contacts"] >= 5)
        ].head(max_flags)

        facility_flags = facility_metrics[
            facility_metrics["flag_any"] & (facility_metrics["n_contacts_total"] >= 10)
        ].head(max_flags)

        # ── Step 3: Build data prompt for Claude ───────────────────────────────
        data_prompt = _build_flagging_prompt(
            df_filtered, counselor_flags, facility_flags, district_metrics, province, district
        )

        # ── Step 4: Generate narrative via Claude ──────────────────────────────
        narrative = ""
        if claude_client.is_configured():
            try:
                narrative = claude_client.call(
                    system_prompt=FLAGGING_SYSTEM_PROMPT,
                    user_prompt=data_prompt,
                    temperature=0.15,
                )
            except Exception as e:
                self.logger.error(f"Claude call failed: {e}")
                narrative = _fallback_narrative(counselor_flags, facility_flags, district_metrics)
        else:
            narrative = _fallback_narrative(counselor_flags, facility_flags, district_metrics)

        return AgentResult(
            agent_name=self.name,
            success=True,
            narrative=narrative,
            data={
                "counselor_metrics": counselor_metrics,
                "facility_metrics": facility_metrics,
                "district_metrics": district_metrics,
                "counselor_flags": counselor_flags,
                "facility_flags": facility_flags,
                "n_contacts": len(df_filtered),
                "n_counselors": df_filtered["counselor"].nunique(),
                "n_facilities": df_filtered["facility"].nunique(),
            },
        )


# ─── Prompt builder ───────────────────────────────────────────────────────────

def _build_flagging_prompt(
    df: pd.DataFrame,
    counselor_flags: pd.DataFrame,
    facility_flags: pd.DataFrame,
    district_metrics: pd.DataFrame,
    province: Optional[str],
    district: Optional[str],
) -> str:
    scope = f"Province: {province or 'All'} | District: {district or 'All'}"
    n_total = len(df)
    n_counselors = df["counselor"].nunique()
    n_facilities = df["facility"].nunique()

    # District baseline summary
    dist_summary = []
    for _, row in district_metrics.iterrows():
        dist_summary.append(
            f"  Distrito {row['district']} ({row['province']}): "
            f"Testados={int(row.get('n_contacts_total', 0)):,} | "
            f"Positividade={cm.format_pct(row.get('district_median_test_positivity', float('nan')))} | "
            f"Conclusao_testagem={cm.format_pct(row.get('district_median_testing_completion', float('nan')))} | "
            f"Contactos_por_caso={cm.format_pct(row.get('district_median_contact_yield', float('nan')))}"
        )
    dist_block = "\n".join(dist_summary) if dist_summary else "  No district data available."

    # Facility flags
    fac_block = "None identified." if len(facility_flags) == 0 else ""
    for _, row in facility_flags.iterrows():
        flags_list = row.get("flags", "")
        fac_block += (
            f"\n  🔴 {row['facility']} ({row['district']}): "
            f"Linkage={cm.format_pct(row.get('median_linkage_rate', float('nan')))} "
            f"(district median: {cm.format_pct(row.get('district_median_linkage_rate', float('nan')))}) | "
            f"Consent={cm.format_pct(row.get('median_consent_rate', float('nan')))} | "
            f"Contacts={int(row.get('n_contacts_total', 0))} | "
            f"Flags: {flags_list}"
        )

    # Counselor flags
    coun_block = "None identified." if len(counselor_flags) == 0 else ""
    for _, row in counselor_flags.iterrows():
        flags_list = row.get("flags", "")
        coun_block += (
            f"\n  {cm.traffic_light(row.get('linkage_rate', float('nan')), row.get('facility_median_linkage_rate', float('nan')))} "
            f"{row['counselor']} at {row['facility']} ({row['district']}): "
            f"Linkage={cm.format_pct(row.get('linkage_rate', float('nan')))} "
            f"(facility median: {cm.format_pct(row.get('facility_median_linkage_rate', float('nan')))}) | "
            f"Consent={cm.format_pct(row.get('consent_rate', float('nan')))} "
            f"(median: {cm.format_pct(row.get('facility_median_consent_rate', float('nan')))}) | "
            f"Contacts={int(row.get('n_contacts', 0))} | "
            f"Positivity={cm.format_pct(row.get('test_positivity', float('nan')))} | "
            f"Flags: {flags_list}"
        )

    # Contact type breakdown
    contact_type_df = cm.stratify_by_contact_type(df)
    ct_block = ""
    for _, row in contact_type_df.iterrows():
        ct_block += (
            f"\n  {row['contact_type']}: n={int(row['n_contacts'])} | "
            f"Positivity={cm.format_pct(row.get('test_positivity', float('nan')))} | "
            f"Linkage={cm.format_pct(row.get('linkage_rate', float('nan')))}"
        )

    return f"""
PERFORMANCE FLAGGING REQUEST
{scope}
Total contacts: {n_total:,} | Counselors: {n_counselors} | Facilities: {n_facilities}

═══ DISTRICT BASELINE METRICS ═══
{dist_block}

═══ FACILITY-LEVEL FLAGS (below district median by ≥10%) ═══
{fac_block}

═══ COUNSELOR-LEVEL FLAGS (below facility median by ≥10%) ═══
{coun_block}

═══ CONTACT TYPE BREAKDOWN ═══
{ct_block}

Please generate a supervision brief following the format specified in your system prompt.
Prioritise FACILITY-level flags first (systemic issues), then COUNSELOR-level flags.
Be specific, practical, and action-oriented. Name every counselor and facility.
"""


def _fallback_narrative(counselor_flags, facility_flags, district_metrics) -> str:
    """Gera narrativa sem Claude se API nao estiver configurada."""
    lines = ["## Resumo de Desempenho (Gerado Automaticamente)\n"]

    if len(district_metrics) > 0:
        for _, row in district_metrics.iterrows():
            lines.append(
                f"**{row['district']}**: Positividade "
                f"{cm.format_pct(row.get('district_median_test_positivity', float('nan')))} | "
                f"Conclusao_testagem {cm.format_pct(row.get('district_median_testing_completion', float('nan')))} | "
                f"Contactos {int(row.get('n_contacts_total', 0)):,}\n"
            )

    if len(facility_flags) > 0:
        lines.append("\n### 🔴 Unidades Sanitarias Sinalizadas\n")
        for _, row in facility_flags.iterrows():
            icon = "🔴" if row.get("severity") == "red" else "🟡"
            lines.append(
                f"- {icon} **{row['facility']}** ({row['district']}): "
                f"Positividade {cm.format_pct(row.get('median_test_positivity', float('nan')))} "
                f"vs mediana distrito {cm.format_pct(row.get('district_median_test_positivity', float('nan')))}\n"
            )

    if len(counselor_flags) > 0:
        lines.append("\n### 🔴 Conselheiros Sinalizados\n")
        for _, row in counselor_flags.iterrows():
            icon = "🔴" if row.get("severity") == "red" else "🟡"
            lines.append(
                f"- {icon} **{row['counselor']}** em {row['facility']}: "
                f"Positividade {cm.format_pct(row.get('test_positivity', float('nan')))} "
                f"vs mediana US {cm.format_pct(row.get('facility_median_test_positivity', float('nan')))}\n"
            )

    if len(facility_flags) == 0 and len(counselor_flags) == 0:
        lines.append("\n✅ Sem sinalizacoes criticas. Todos os conselheiros e unidades estao em dia.\n")

    lines.append("\n*Nota: Configure GROK_API_KEY para activar narrativas geradas por IA.*")
    return "".join(lines)
