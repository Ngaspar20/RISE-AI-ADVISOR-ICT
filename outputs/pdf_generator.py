"""
pdf_generator.py  v3
─────────────────────
Relatório de supervisão ICT RISE com prioridades contextualizadas.

Cada card explica PORQUE é prioridade:
  - Volume real: contactos testados + positivos encontrados
  - Positivos esperados vs encontrados (gap de impacto)
  - Tendência das últimas semanas (a piorar / estável / a melhorar)
  - Pontuação de urgência composta (gap x volume x tendência)
  - Lista de verificação contextual ao padrão observado
"""

import logging
import numpy as np
import pandas as pd
from datetime import date
from typing import Optional, Tuple
from fpdf import FPDF

logger = logging.getLogger(__name__)

# ── Caracteres especiais para latin-1 ───────────────────────────────────────
_UMAP = {
    "—": "-", "–": "-",
    "‘": "'", "’": "'",
    "“": '"', "”": '"',
    "…": "...",
    "↑": "[^]", "↓": "[v]", "→": "[=]",
}
def _s(text) -> str:
    text = str(text) if not isinstance(text, str) else text
    for ch, r in _UMAP.items():
        text = text.replace(ch, r)
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ── Paleta de cores ──────────────────────────────────────────────────────────
BLUE   = (0, 83, 156)
LBLUE  = (220, 235, 250)
WHITE  = (255, 255, 255)
GRAY   = (110, 110, 110)
LGRAY  = (245, 247, 250)
DKGRAY = (40, 40, 40)
RED    = (180, 0, 0)
RED_BG = (255, 235, 235)
YEL_BG = (255, 252, 215)
GRN_BG = (235, 250, 240)
GRN    = (20, 130, 60)
ORANGE = (200, 90, 0)


# ── Tendência: período actual vs 4 semanas anteriores ───────────────────────
def _facility_trend(df_current, df_prev, facility: str) -> Tuple[str, float, str]:
    """
    Compara positividade do período actual (2 semanas) com o período anterior (4 semanas).
    df_current = df já filtrado ao período de análise
    df_prev    = df das 4 semanas anteriores
    """
    def prate(df_sub, fac):
        if df_sub is None: return None
        s = df_sub[df_sub["facility"] == fac]
        t = s["was_tested"].sum(); p = s["is_positive"].sum()
        return round(p / t * 100, 1) if t > 0 else None

    r_act  = prate(df_current, facility)
    r_prev = prate(df_prev,    facility)

    if r_act is None:
        return "sem_dados", 0.0, "Sem dados de teste no periodo actual para esta US."
    if r_prev is None:
        return "sem_dados", 0.0, f"Positividade actual: {r_act:.1f}% — sem dados anteriores para comparar."

    chg  = round(r_act - r_prev, 1)
    desc = f"Periodo actual: {r_act:.1f}%  vs  4 semanas anteriores: {r_prev:.1f}%"

    if chg < -1.5:  return "piorar",   chg, desc + " — A PIORAR"
    elif chg > 1.5: return "melhorar", chg, desc + " — A MELHORAR"
    else:           return "estavel",  chg, desc + " — ESTAVEL"


# ── Pontuação de urgência ────────────────────────────────────────────────────
def _urgency_score(pos: float, ref: float, n_tested: int, trend: str) -> float:
    try:
        gap_rel = max(0.0, (float(ref) - float(pos)) / max(float(ref), 0.1))
        vol_w   = min(1.0, np.log10(max(int(n_tested), 1) + 1) / np.log10(501))
        t_mult  = 1.35 if trend == "piorar" else (0.75 if trend == "melhorar" else 1.0)
        return round(gap_rel * vol_w * t_mult * 100, 0)
    except:
        return 0.0


# ── Positivos esperados ──────────────────────────────────────────────────────
def _expected(n_tested: int, ref_pct: float, n_real: int) -> Tuple[int, int]:
    try:
        esp = round(int(n_tested) * float(ref_pct) / 100)
        return esp, max(0, esp - int(n_real))
    except:
        return 0, 0


# ── PDF base ─────────────────────────────────────────────────────────────────
class SupervisionPDF(FPDF):
    def __init__(self, scope: str, report_date: date):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.scope = scope; self.report_date = report_date
        self.set_auto_page_break(auto=True, margin=16)
        self.set_margins(12, 15, 12)
        self.add_page()

    def header(self):
        self.set_fill_color(*BLUE); self.rect(0, 0, 210, 14, "F")
        self.set_font("Helvetica", "B", 9); self.set_text_color(*WHITE)
        self.set_y(3); self.cell(0, 8, "RISE ICT  |  Resumo Semanal de Supervisao", align="C")
        self.set_y(14)

    def footer(self):
        self.set_y(-10); self.set_font("Helvetica", "", 7); self.set_text_color(*GRAY)
        txt = f"JHPIEGO RISE  |  {self.report_date.strftime('%d %b %Y')}  |  Confidencial  |  Pag. {self.page_no()}"
        self.cell(0, 5, _s(txt), align="C")

    def section_title(self, title: str):
        self.ln(2); self.set_fill_color(*BLUE); self.set_text_color(*WHITE)
        self.set_font("Helvetica", "B", 9)
        self.cell(0, 7, f"  {_s(title)}", fill=True, ln=True)
        self.set_text_color(*DKGRAY); self.ln(1)


# ── API pública ──────────────────────────────────────────────────────────────
def generate_supervisor_brief(
    flagging_result, allocation_result,
    province: str = "", district: str = "",
    report_date=None,
    df=None,            # df_period: 2 semanas actuais (métricas + volumes)
    df_prev=None,       # df_trend:  4 semanas anteriores (para tendência)
    period_start=None,  # date: início do período
    period_end=None,    # date: fim do período
) -> bytes:
    report_date = report_date or date.today()
    scope = f"{province} — {district}" if district else province or "Todas as Provincias"
    pdf   = SupervisionPDF(scope, report_date)

    pdf.set_y(17)
    pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(*BLUE)
    pdf.cell(0, 7, _s(scope), ln=True)
    pdf.set_font("Helvetica", "", 8); pdf.set_text_color(*GRAY)
    # Mostrar período de análise explicitamente
    if period_start and period_end:
        periodo_str = (
            f"Periodo de analise: {period_start.strftime('%d/%m/%Y')} "
            f"a {period_end.strftime('%d/%m/%Y')}  (2 semanas)"
        )
    else:
        periodo_str = f"Gerado em: {report_date.strftime('%d de %B de %Y')}"
    pdf.cell(0, 4, _s(periodo_str), ln=True)
    pdf.ln(2)

    data_f = flagging_result.data  if (flagging_result  and flagging_result.success)  else {}
    data_a = allocation_result.data if (allocation_result and allocation_result.success) else {}

    pdf.section_title("1. RESUMO GERAL DO PROGRAMA")
    _section_summary(pdf, data_f.get("district_metrics", pd.DataFrame()), df)

    pdf.section_title("2. PRIORIDADES DESTA SEMANA — PORQUE SAO PRIORITARIAS")
    _section_priorities(pdf,
                        data_f.get("facility_flags",  pd.DataFrame()),
                        data_f.get("counselor_flags", pd.DataFrame()),
                        df, df_prev)

    pdf.section_title("3. PLANO DE VISITAS SEMANAL")
    _section_visits(pdf, data_a.get("triage", {}), df)

    return bytes(pdf.output())


# ── Sec. 1: Resumo ───────────────────────────────────────────────────────────
def _section_summary(pdf, dm: pd.DataFrame, df):
    W = pdf.w - pdf.l_margin - pdf.r_margin

    if df is not None:
        n_cont  = len(df)
        n_test  = int(df["was_tested"].sum())
        n_pos   = int(df["is_positive"].sum())
        pos_g   = round(n_pos / n_test * 100, 1) if n_test > 0 else 0.0
        n_cons  = int(df["consented"].sum()) if "consented" in df.columns else 0
        cons_g  = round(n_cons / max(n_cont, 1) * 100, 1)
    else:
        n_cont = n_test = n_pos = 0; pos_g = cons_g = 0.0

    kpis = [
        ("Contactos\nregistados", f"{n_cont:,}",   None),
        ("Contactos\ntestados",   f"{n_test:,}",   None),
        ("HIV+\nencontrados",     str(n_pos),       RED if n_pos == 0 else None),
        ("Positividade\nglobal",  f"{pos_g:.1f}%",  RED if pos_g < 1.0 else (GRN if pos_g >= 3.0 else ORANGE)),
        ("Consentimento\nglobal", f"{cons_g:.1f}%", RED if cons_g < 80 else (GRN if cons_g >= 90 else ORANGE)),
    ]
    cw = W / len(kpis); x0, y0 = pdf.get_x(), pdf.get_y()
    for i, (lbl, val, col) in enumerate(kpis):
        pdf.set_xy(x0 + i * cw, y0)
        pdf.set_fill_color(*LBLUE); pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(*(col or BLUE))
        pdf.cell(cw - 1, 8, _s(val), border=1, fill=True, align="C")
        pdf.set_xy(x0 + i * cw, y0 + 8)
        pdf.set_font("Helvetica", "", 6.5); pdf.set_text_color(*GRAY)
        for line in lbl.split("\n"):
            pdf.cell(cw - 1, 3, _s(line), align="C")
            pdf.set_xy(x0 + i * cw, pdf.get_y() + 3)
    pdf.set_xy(x0, y0 + 15); pdf.ln(3); pdf.set_text_color(*DKGRAY)

    if dm.empty:
        pdf.set_font("Helvetica", "I", 8)
        pdf.cell(0, 5, "Sem dados de distrito disponiveis.", ln=True); return

    cw2  = [50, 22, 24, 30, 26, 26]
    hdrs = ["Distrito", "HIV+ encontr.", "Testados", "Positividade %", "Testagem %", "Consentim. %"]
    pdf.set_fill_color(*LBLUE); pdf.set_font("Helvetica", "B", 7.5); pdf.set_text_color(*DKGRAY)
    for h, w in zip(hdrs, cw2):
        pdf.cell(w, 5.5, _s(h), border=1, fill=True, align="C")
    pdf.ln()

    for _, row in dm.iterrows():
        dist = row.get("district", "")
        if df is not None:
            ds = df[df["district"] == dist]
            dp   = int(ds["is_positive"].sum())
            dt   = int(ds["was_tested"].sum())
            dpr  = round(dp / dt * 100, 1) if dt > 0 else 0.0
            elig = int(ds["eligible_bool"].sum()) if "eligible_bool" in ds.columns else dt
            dtp  = round(dt / max(elig, 1) * 100, 1)
            cons = int(ds["consented"].sum()) if "consented" in ds.columns else elig
            dcp  = round(cons / max(elig, 1) * 100, 1)
        else:
            dp = dt = 0; dpr = dtp = dcp = 0.0

        pdf.set_font("Helvetica", "", 7.5); pdf.set_text_color(*DKGRAY)
        pdf.set_fill_color(*WHITE)
        pdf.cell(cw2[0], 4.5, _s(f"  {dist}"), border=1)
        pdf.cell(cw2[1], 4.5, _s(str(dp)),     border=1, align="C")
        pdf.cell(cw2[2], 4.5, _s(f"{dt:,}"),   border=1, align="C")
        p_bg = RED_BG if dpr < 1.5 else (GRN_BG if dpr >= 4.0 else YEL_BG)
        pdf.set_fill_color(*p_bg)
        pdf.cell(cw2[3], 4.5, _s(f"{dpr:.1f}%"), border=1, align="C", fill=True)
        t_bg = GRN_BG if dtp >= 90 else (YEL_BG if dtp >= 70 else RED_BG)
        pdf.set_fill_color(*t_bg)
        pdf.cell(cw2[4], 4.5, _s(f"{dtp:.1f}%"), border=1, align="C", fill=True)
        c_str = f"{dcp:.1f}%" + (" (!)" if dcp > 100 else "")
        c_bg  = GRN_BG if 90 <= dcp <= 100 else (YEL_BG if dcp >= 75 else RED_BG)
        pdf.set_fill_color(*c_bg)
        pdf.cell(cw2[5], 4.5, _s(c_str), border=1, align="C", fill=True)
        pdf.set_fill_color(*WHITE); pdf.ln()

    pdf.set_text_color(*GRAY); pdf.set_font("Helvetica", "I", 6.5)
    pdf.cell(0, 4, "Legenda: Verde = bom  |  Amarelo = atencao  |  Vermelho = accao urgente", ln=True)
    pdf.set_text_color(*DKGRAY)


# ── Sec. 2: Prioridades ──────────────────────────────────────────────────────
def _section_priorities(pdf, fac_flags: pd.DataFrame, coun_flags: pd.DataFrame, df, df_prev=None):
    if fac_flags.empty and coun_flags.empty:
        pdf.set_font("Helvetica", "B", 9); pdf.set_text_color(*GRN)
        pdf.cell(0, 6, "Sem problemas criticos identificados. Todas as unidades em dia.", ln=True)
        pdf.set_text_color(*DKGRAY); return

    items = []

    for _, row in fac_flags.iterrows():
        fac   = row.get("facility", "")
        pos   = float(row.get("median_test_positivity", 0) or 0)
        d_med = float(row.get("district_median_test_positivity", max(pos + 0.1, 1)) or 1)
        sev   = row.get("severity", "yellow")
        flags = str(row.get("flags", ""))
        n_tested = n_pos_real = 0
        if df is not None:
            sub = df[df["facility"] == fac]
            n_tested  = int(sub["was_tested"].sum())
            n_pos_real= int(sub["is_positive"].sum())
        n_cont = int(row.get("n_contacts_total", n_tested) or n_tested)
        trend_dir, trend_chg, trend_desc = _facility_trend(df, df_prev, fac)
        score = _urgency_score(pos, d_med, n_tested, trend_dir)
        esp, em_falta = _expected(n_tested, d_med, n_pos_real)
        items.append(dict(tipo="facility", row=row, score=score, fac=fac,
                          dist=row.get("district",""), sev=sev, flags=flags,
                          pos=pos, d_med=d_med, n_cont=n_cont,
                          n_tested=n_tested, n_pos_real=n_pos_real,
                          esp=esp, em_falta=em_falta,
                          trend_dir=trend_dir, trend_chg=trend_chg, trend_desc=trend_desc))

    for _, row in coun_flags.iterrows():
        name    = (str(row.get("counselor","")) or "").strip() or "[nome em falta]"
        fac     = row.get("facility", "")
        pos     = float(row.get("test_positivity", 0) or 0)
        f_med   = float(row.get("facility_median_test_positivity", max(pos+0.1,1)) or 1)
        n_cont  = int(row.get("n_contacts", 0) or 0)
        n_pos_r = int(row.get("n_positive", 0) or 0)
        n_test_c= int(row.get("n_tested", n_cont) or n_cont)
        sev     = row.get("severity", "yellow")
        flags   = str(row.get("flags", ""))
        esp, em_falta = _expected(n_test_c, f_med, n_pos_r)
        score = _urgency_score(pos, f_med, n_test_c, "sem_dados") * 0.85
        items.append(dict(tipo="counselor", row=row, score=score,
                          name=name, fac=fac, dist=row.get("district",""),
                          sev=sev, flags=flags, pos=pos, d_med=f_med,
                          n_cont=n_cont, n_tested=n_test_c, n_pos_real=n_pos_r,
                          esp=esp, em_falta=em_falta,
                          trend_dir="sem_dados", trend_chg=0.0,
                          trend_desc="Tendencia individual requer analise do historico por conselheiro."))

    items.sort(key=lambda x: -x["score"])

    n_crit  = sum(1 for i in items if i["sev"] == "red")
    n_atenc = sum(1 for i in items if i["sev"] == "yellow")
    pdf.set_font("Helvetica", "", 8); pdf.set_text_color(*DKGRAY)
    pdf.cell(0, 5, _s(
        f"Identificadas {n_crit} unidade(s)/conselheiro(s) CRITICO(S) e {n_atenc} em ATENCAO. "
        "Ordenados por pontuacao de urgencia (gap x volume x tendencia)."
    ), ln=True)
    pdf.ln(1)

    for idx, item in enumerate(items[:10]):
        _draw_card(pdf, item, idx + 1)
        pdf.ln(2)
    pdf.set_text_color(*DKGRAY)


def _draw_card(pdf, item: dict, rank: int):
    sev   = item["sev"]
    bg    = RED_BG if sev == "red" else YEL_BG
    label = "CRITICO" if sev == "red" else "ATENCAO"
    score = item["score"]
    td    = item["trend_dir"]
    t_col = RED if td == "piorar" else (GRN if td == "melhorar" else GRAY)
    t_sym = {"piorar":"[v] A PIORAR","melhorar":"[^] A MELHORAR",
              "estavel":"[=] ESTAVEL","sem_dados":"sem dados de tendencia"}

    # Cabeçalho
    pdf.set_fill_color(*bg); pdf.set_font("Helvetica", "B", 8.5); pdf.set_text_color(*DKGRAY)
    if item["tipo"] == "facility":
        titulo = f"#{rank}  [{label}]  US: {item['fac']}  ({item['dist']})"
    else:
        titulo = f"#{rank}  [{label}]  CONSELHEIRO: {item['name']}  |  {item['fac']}  ({item['dist']})"
    pdf.cell(0, 6.5, _s(titulo), fill=True, border=1, ln=True)

    # Sub-cabeçalho pontuação + tendência
    W = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.set_fill_color(245, 245, 245)
    pdf.set_font("Helvetica", "", 7); pdf.set_text_color(*GRAY)
    pdf.cell(W * 0.45, 4, _s(f"  Pontuacao de urgencia: {score:.0f}/100"), border="LB", fill=True)
    pdf.set_font("Helvetica", "B", 7); pdf.set_text_color(*t_col)
    pdf.cell(W * 0.55, 4, _s(f"  {t_sym.get(td,'')}"), border="RB", fill=True, ln=True)

    # Corpo
    pdf.set_fill_color(252, 254, 255)

    # Rótulo "Porque é prioridade"
    pdf.set_font("Helvetica", "B", 7.5); pdf.set_text_color(*BLUE)
    pdf.cell(0, 5, "  PORQUE E PRIORITARIO:", fill=True, border="LR", ln=True)

    pdf.set_font("Helvetica", "", 7.5); pdf.set_text_color(*DKGRAY)
    pos  = item["pos"]; d_med = item["d_med"]
    nt   = item["n_tested"]; np_r = item["n_pos_real"]
    esp  = item["esp"];  emf = item["em_falta"]
    gpp  = round(d_med - pos, 1)
    ref  = "mediana do distrito" if item["tipo"]=="facility" else "mediana da US"

    # Linha 1 — volume e positivos reais
    l1 = (f"  Esta US testou {nt:,} contactos e encontrou {np_r} HIV+ (positividade real: {pos:.1f}%)"
          if item["tipo"]=="facility"
          else f"  Este conselheiro acompanhou {nt:,} contactos e encontrou {np_r} HIV+ (positividade: {pos:.1f}%)")
    pdf.cell(0, 4.5, _s(l1), fill=True, border="LR", ln=True)

    # Linha 2 — gap vs mediana
    l2 = f"  {ref.capitalize()}: {d_med:.1f}%  ->  Esta US esta {gpp:.1f} pontos percentuais ABAIXO da referencia"
    pdf.cell(0, 4.5, _s(l2), fill=True, border="LR", ln=True)

    # Linha 3 — impacto (destaque)
    pdf.set_font("Helvetica", "B", 7.5)
    if nt >= 10 and esp > 0 and emf > 0:
        pdf.set_text_color(*RED)
        l3 = (f"  IMPACTO: Com {nt} contactos testados, esperaríamos ~{esp} HIV+  "
              f"->  Estao potencialmente em falta ~{emf} casos nao identificados")
    elif pos == 0 and nt >= 10:
        pdf.set_text_color(*RED)
        l3 = f"  ALERTA: Zero positivos em {nt} contactos testados — verificar urgentemente a qualidade do registo"
    else:
        pdf.set_text_color(*DKGRAY)
        l3 = f"  Com {nt} contactos testados, o impacto desta lacuna e significativo para o programa"
    pdf.cell(0, 4.5, _s(l3), fill=True, border="LR", ln=True)
    pdf.set_font("Helvetica", "", 7.5)

    # Linha 4 — tendência
    pdf.set_text_color(*t_col)
    pdf.cell(0, 4.5, _s(f"  Tendencia: {item['trend_desc']}"), fill=True, border="LR", ln=True)
    pdf.set_text_color(*DKGRAY)

    # Outros flags
    outros = [f.strip() for f in item["flags"].split() if f.strip() != "test_positivity" and f.strip()]
    if outros:
        mapa = {"testing_completion":"testagem incompleta",
                "contact_yield":"poucos contactos por caso indice",
                "consent_rate":"consentimento baixo"}
        pdf.set_text_color(*ORANGE)
        pdf.cell(0, 4.5, _s(f"  Outros problemas: {', '.join(mapa.get(f,f) for f in outros)}"),
                 fill=True, border="LR", ln=True)
        pdf.set_text_color(*DKGRAY)

    # Acções
    pdf.set_font("Helvetica", "B", 7.5); pdf.set_text_color(*BLUE)
    visita = "Revisao de unidade (dia completo)" if sev=="red" else "Visita de coaching (meio dia)"
    pdf.cell(0, 5, _s(f"  ACCAO RECOMENDADA: {visita}"), fill=True, border="LR", ln=True)

    pdf.set_font("Helvetica", "", 7.5); pdf.set_text_color(*DKGRAY)
    for chk in _checklist(item)[:5]:
        pdf.cell(0, 4.5, _s(f"  [ ] {chk}"), fill=True, border="LR", ln=True)

    # Borda inferior
    pdf.set_fill_color(*bg); pdf.cell(0, 1.5, "", fill=True, border=1, ln=True)
    pdf.set_fill_color(*WHITE)


def _checklist(item: dict) -> list:
    pos = item["pos"]; d_med = item["d_med"]
    nt  = item["n_tested"]; td = item["trend_dir"]; flags = item["flags"]
    checks = []
    if pos == 0 and nt >= 10:
        checks += [
            "Verificar no DHIS2 se os resultados dos testes estao a ser inseridos correctamente",
            "Confirmar validade dos kits de teste e tecnica de aplicacao pelo laboratorista",
            "Rever os contactos elicitados: sao predominantemente parceiros sexuais de risco elevado?",
            "Entrevistar o conselheiro: quais sao as maiores dificuldades na elicitacao de contactos?",
        ]
    elif pos < d_med * 0.5:
        checks += [
            f"Qualidade da elicitacao: o conselheiro esta a identificar TODOS os parceiros sexuais do caso indice?",
            "Analisar a composicao dos contactos (parceiros vs filhos) — filhos tem taxa de positividade menor",
            "Confirmar que 100% dos testes realizados tem resultado registado no sistema",
            f"Partilhar praticas das US com maior positividade (mediana do distrito: {d_med:.1f}%)",
        ]
    else:
        checks += [
            "Identificar 1-2 conselheiros com menor desempenho e fazer sessao de coaching individual",
            "Verificar se ha barreiras ao consentimento que reduzem o numero de contactos elegíveis testados",
            "Discutir com o chefe clinico: ha factores locais que explicam positividade abaixo da mediana?",
        ]
    if td == "piorar":
        checks.append("URGENTE: Tendencia a piorar — identificar o que mudou (novo conselheiro? nova area de captacao?)")
    if "contact_yield" in flags:
        checks.append("Poucos contactos por caso: rever tecnica de entrevista — o utente esta a listar TODOS os parceiros?")
    if "consent_rate" in flags:
        checks.append("Consentimento baixo: rever abordagem pre-teste — usar mensagens de beneficio pessoal para a saude")
    if "testing_completion" in flags:
        checks.append("Testagem incompleta: verificar disponibilidade de kits e agendamento de contactos para teste")
    return checks


# ── Sec. 3: Plano de visitas ─────────────────────────────────────────────────
def _section_visits(pdf, triage: dict, df):
    red_l    = triage.get("red", [])
    yellow_l = triage.get("yellow", [])
    if not red_l and not yellow_l:
        pdf.set_font("Helvetica", "I", 8)
        pdf.cell(0, 5, "Sem visitas urgentes identificadas esta semana.", ln=True); return

    W   = pdf.w - pdf.l_margin - pdf.r_margin
    cw  = [52, 30, 42, W - 52 - 30 - 42]
    hdrs= ["Unidade Sanitaria", "Distrito", "Tipo de Visita", "Prioridade / Justificacao"]
    pdf.set_fill_color(*LBLUE); pdf.set_font("Helvetica", "B", 7.5); pdf.set_text_color(*DKGRAY)
    for h, w in zip(hdrs, cw):
        pdf.cell(w, 5.5, _s(h), border=1, fill=True, align="C")
    pdf.ln()

    def get_pr(fac):
        if df is None: return None
        s = df[df["facility"]==fac]; t=s["was_tested"].sum(); p=s["is_positive"].sum()
        return round(p/t*100,1) if t>0 else 0.0

    for e in red_l:
        fac=e.get("facility",""); dist=e.get("district","")
        vt=e.get("suggested_visit_type","Revisao de unidade")
        pr=get_pr(fac)
        just = f"ESTA SEMANA — positividade {pr:.1f}% (abaixo da mediana)" if pr is not None else "ESTA SEMANA"
        pdf.set_fill_color(*RED_BG); pdf.set_font("Helvetica","",7.5); pdf.set_text_color(*DKGRAY)
        pdf.cell(cw[0],4.5,_s(f"  {fac}"),border=1,fill=True)
        pdf.cell(cw[1],4.5,_s(dist),border=1,fill=True,align="C")
        pdf.cell(cw[2],4.5,_s(vt),border=1,fill=True)
        pdf.cell(cw[3],4.5,_s(just),border=1,fill=True); pdf.ln()

    for e in yellow_l[:4]:
        fac=e.get("facility",""); dist=e.get("district","")
        vt=e.get("suggested_visit_type","Visita de coaching")
        pdf.set_fill_color(*YEL_BG); pdf.set_font("Helvetica","",7.5); pdf.set_text_color(*DKGRAY)
        pdf.cell(cw[0],4.5,_s(f"  {fac}"),border=1,fill=True)
        pdf.cell(cw[1],4.5,_s(dist),border=1,fill=True,align="C")
        pdf.cell(cw[2],4.5,_s(vt),border=1,fill=True)
        pdf.cell(cw[3],4.5,"ESTE MES",border=1,fill=True); 