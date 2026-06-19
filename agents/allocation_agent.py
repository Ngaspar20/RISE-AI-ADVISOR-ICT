"""
allocation_agent.py
───────────────────
WORKFLOW 2: Supervision Resource Allocation

Answers: "Where should we deploy supervision resources this week/month?"

Logic:
  1. Triage by urgency (Red/Yellow/Green)
  2. Batch by geography
  3. Match supervision type to root cause
  4. Generate weekly supervision plan via Claude
"""

import pandas as pd
import numpy as np
import logging
from typing import Optional, List

from agents.base_agent import BaseAgent, AgentResult, RISE_CONTEXT
from tools import compute_metrics as cm
from tools import claude_client

logger = logging.getLogger(__name__)

ALLOCATION_SYSTEM_PROMPT = f"""{RISE_CONTEXT}

És o AGENTE DE ALOCAÇÃO DE SUPERVISÃO do programa RISE ICT.

Foco: volume de testagem e positividade. A linkagem não é prioritária.

Tipos de visita:
  - VISITA DE COACHING (2-4h): gap individual de um conselheiro
  - REVISÃO DE UNIDADE (dia completo): problemas sistémicos de testagem
  - APRENDIZAGEM ENTRE PARES (meio dia): mentor de melhor desempenho para colegas

Critérios de triagem:
  - 🔴 VERMELHO (visitar esta semana): positividade muito baixa OU conclusão de testagem <70%
  - 🟡 AMARELO (visitar este mês): sinais de alerta, ainda não críticos
  - 🟢 VERDE (manutenção trimestral): a funcionar bem

## PLANO DE SUPERVISÃO SEMANAL

### Esta Semana (🔴 Crítico — visita obrigatória)
| Unidade | Distrito | Tipo de Visita | Duração | Conselheiros a Apoiar | Indicador Prioritário | Motivo |
|---------|----------|---------------|---------|----------------------|----------------------|--------|
[Preencher tabela]

### Este Mês (🟡 Atenção — agendar nas próximas 4 semanas)
[Lista resumida: unidade, tipo, motivo em 1 frase]

### Em Dia (🟢 — verificação trimestral)
[Lista de unidades, 1 linha cada]

### Lista de Verificação — Visitas Críticas
Para cada visita vermelha, 3 coisas a observar:
[Nome da unidade]:
  □ [Observação 1]
  □ [Observação 2]
  □ [Observação 3]

Responde SEMPRE em Português.
"""

class AllocationAgent(BaseAgent):
    """Generates weekly supervision resource allocation plan."""

    def __init__(self):
        super().__init__("AllocationAgent")

    def run(
        self,
        df: pd.DataFrame,
        province: Optional[str] = None,
        district: Optional[str] = None,
        n_supervisors: int = 2,
        visits_per_week: int = 3,
    ) -> AgentResult:
        """
        Generate a supervision allocation plan.

        Parameters
        ----------
        df               : Full normalised ICT line-list
        province         : Filter to province (optional)
        district         : Filter to district (optional)
        n_supervisors    : Available supervisors for scheduling
        visits_per_week  : Max facility visits per week (travel constraint)
        """
        df_filtered = self._filter_df(df, province=province, district=district)
        if len(df_filtered) == 0:
            return AgentResult(
                agent_name=self.name, success=False,
                narrative="No data for selected filters.", error="Empty dataset"
            )

        self.logger.info(
            f"Running AllocationAgent: province={province} district={district} | "
            f"n={len(df_filtered):,}"
        )

        # ── Compute metrics and flags ──────────────────────────────────────────
        counselor_flags = cm.flag_counselors(df_filtered)
        facility_flags = cm.flag_facilities(df_filtered)

        # ── Triage facilities ──────────────────────────────────────────────────
        triage = _triage_facilities(facility_flags, counselor_flags)

        # ── Build prompt ───────────────────────────────────────────────────────
        data_prompt = _build_allocation_prompt(
            df_filtered, triage, counselor_flags, n_supervisors, visits_per_week,
            province, district
        )

        # ── Generate narrative ─────────────────────────────────────────────────
        narrative = ""
        if claude_client.is_configured():
            try:
                narrative = claude_client.call(
                    system_prompt=ALLOCATION_SYSTEM_PROMPT,
                    user_prompt=data_prompt,
                    temperature=0.15,
                    max_tokens=2048,
                )
            except Exception as e:
                self.logger.error(f"Claude call failed: {e}")
                narrative = _fallback_allocation(triage)
        else:
            narrative = _fallback_allocation(triage)

        return AgentResult(
            agent_name=self.name,
            success=True,
            narrative=narrative,
            data={
                "triage": triage,
                "counselor_flags": counselor_flags,
                "facility_flags": facility_flags,
                "n_red": len(triage["red"]),
                "n_yellow": len(triage["yellow"]),
                "n_green": len(triage["green"]),
            },
        )


# ─── Triage logic ─────────────────────────────────────────────────────────────

def _triage_facilities(
    facility_flags: pd.DataFrame, counselor_flags: pd.DataFrame
) -> dict:
    """Sort facilities into Red / Yellow / Green triage buckets."""
    red, yellow, green = [], [], []

    for _, row in facility_flags.iterrows():
        positivity = row.get("median_test_positivity", float("nan"))
        testing_comp = row.get("median_testing_completion", float("nan"))
        severity = row.get("severity", "green")
        flag_any = row.get("flag_any", False)

        # Count how many counselors at this facility are flagged
        facility_counselor_flags = counselor_flags[
            counselor_flags["facility"] == row["facility"]
        ]
        n_flagged_counselors = facility_counselor_flags["flag_any"].sum()
        n_total_counselors = len(facility_counselor_flags)

        entry = {
            "facility": row["facility"],
            "district": row["district"],
            "province": row.get("province", ""),
            "positivity": positivity,
            "testing_completion": testing_comp,
            "linkage_rate": row.get("median_linkage_rate", float("nan")),
            "consent_rate": row.get("median_consent_rate", float("nan")),
            "n_contacts": int(row.get("n_contacts_total", 0)),
            "n_counselors": int(n_total_counselors),
            "n_flagged_counselors": int(n_flagged_counselors),
            "flags": row.get("flags", ""),
            "severity": severity,
            "suggested_visit_type": _suggest_visit_type(row, n_flagged_counselors, n_total_counselors),
        }

        # Triage by testing volume / positivity gap
        low_volume = not pd.isna(testing_comp) and testing_comp < 70
        if severity == "red" or low_volume:
            red.append(entry)
        elif severity == "yellow" or flag_any:
            yellow.append(entry)
        else:
            green.append(entry)

    return {"red": red, "yellow": yellow, "green": green}


def _suggest_visit_type(row, n_flagged: int, n_total: int) -> str:
    """Determine the appropriate supervision visit type."""
    if n_total == 0:
        return "Facility Review"
    frac_flagged = n_flagged / n_total if n_total > 0 else 0

    if frac_flagged >= 0.5:
        # More than half of counselors flagged → systemic facility issue
        return "Facility Review (full day)"
    elif n_flagged == 1:
        return "Coaching Visit (2-4 hours)"
    elif n_flagged > 1:
        return "Peer Learning + Coaching (half day)"
    else:
        return "Facility Review (half day)"


def _build_allocation_prompt(
    df: pd.DataFrame, triage: dict, counselor_flags: pd.DataFrame,
    n_supervisors: int, visits_per_week: int,
    province: Optional[str], district: Optional[str]
) -> str:
    scope = f"Province: {province or 'All'} | District: {district or 'All'}"

    def fmt_list(entries: List[dict]) -> str:
        if not entries:
            return "  None"
        lines = []
        for e in entries:
            # Get flagged counselors at this facility
            fc = counselor_flags[counselor_flags["facility"] == e["facility"]]
            flagged_names = fc[fc["flag_any"]]["counselor"].tolist()[:3]
            names_str = ", ".join(flagged_names) if flagged_names else "all performing adequately"
            lines.append(
                f"  {e['facility']} ({e['district']}) | "
                f"Positividade={cm.format_pct(e['positivity'])} | "
                f"Conclusao_testagem={cm.format_pct(e['testing_completion'])} | "
                f"Contactos={e['n_contacts']} | "
                f"Flagged counselors ({e['n_flagged_counselors']}/{e['n_counselors']}): {names_str} | "
                f"Suggested: {e['suggested_visit_type']} | "
                f"Flags: {e['flags'] or 'none'}"
            )
        return "\n".join(lines)

    return f"""
SUPERVISION ALLOCATION REQUEST
{scope}

Constraints:
  - Available supervisors: {n_supervisors}
  - Max visits per week: {visits_per_week}
  - Total facilities to manage: {len(triage['red']) + len(triage['yellow']) + len(triage['green'])}

═══ 🔴 RED — CRITICAL (visit this week) ═══
{fmt_list(triage['red'])}

═══ 🟡 YELLOW — CAUTION (visit this month) ═══
{fmt_list(triage['yellow'])}

═══ 🟢 GREEN — ON TRACK (quarterly) ═══
{fmt_list(triage['green'])}

Please generate a practical weekly supervision plan.
Batch facilities by district to minimise travel.
Specify visit type, duration, and 3 things to observe for each red-flag visit.
"""


def _fallback_allocation(triage: dict) -> str:
    lines = ["## Plano de Supervisão Semanal\n\n"]

    if triage["red"]:
        lines.append("### 🔴 Visitar Esta Semana\n")
        for e in triage["red"]:
            lines.append(
                f"- **{e['facility']}** ({e['district']}): "
                f"Positividade {cm.format_pct(e.get('positivity', float('nan')))} | "
                f"{e['suggested_visit_type']}\n"
            )

    if triage["yellow"]:
        lines.append("\n### 🟡 Agendar Este Mês\n")
        for e in triage["yellow"]:
            lines.append(
                f"- **{e['facility']}** ({e['district']}): "
                f"Positividade {cm.format_pct(e.get('positivity', float('nan')))} | "
                f"{e['suggested_visit_type']}\n"
            )

    if triage["green"]:
        lines.append("\n### 🟢 Em Dia (Trimestral)\n")
        for e in triage["green"]:
            lines.append(f"- {e['facility']} ({e['district']})\n")

    lines.append("\n*Configure GROK_API_KEY for AI-generated supervision plans.*")
    return "".join(lines)
