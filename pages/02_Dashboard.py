"""
02_Dashboard.py
───────────────
Página 2: Painel de Desempenho Interactivo
Foco: volume de testagem, positividade, positivos encontrados
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.compute_metrics import (
    compute_counselor_metrics, compute_facility_metrics,
    compute_district_metrics, compute_weekly_trends,
    stratify_by_contact_type, stratify_by_age_group,
    flag_counselors, flag_facilities,
    format_pct, traffic_light,
)

st.set_page_config(page_title="Painel — RISE ICT", page_icon="📊", layout="wide")

if st.session_state.get("df") is None:
    st.warning("⚠️ Nenhum dado carregado. Por favor carregue um CSV primeiro.")
    if st.button("→ Ir para Upload"):
        st.switch_page("pages/01_Upload.py")
    st.stop()

df_full = st.session_state.df

# ─── Filtros ──────────────────────────────────────────────────────────────────
st.sidebar.markdown("### 🔽 Filtros")

provinces = ["Todas"] + sorted(df_full["province"].dropna().unique().tolist())
sel_province = st.sidebar.selectbox("Província", provinces)

df_prov = df_full if sel_province == "Todas" else df_full[df_full["province"] == sel_province]

districts = ["Todos"] + sorted(df_prov["district"].dropna().unique().tolist())
sel_district = st.sidebar.selectbox("Distrito", districts)

df_filtered = df_prov if sel_district == "Todos" else df_prov[df_prov["district"] == sel_district]

st.sidebar.markdown("---")
view_level = st.sidebar.radio("Nível de Visualização", ["Distrito", "Unidade Sanitária", "Conselheiro"], index=0)

# ─── Cabeçalho ────────────────────────────────────────────────────────────────
scope = " → ".join(filter(lambda x: x not in ("Todas", "Todos"), [sel_province, sel_district])) or "Todas as Províncias"
st.markdown(f"## 📊 Painel de Desempenho: {scope}")
st.markdown(f"*{len(df_filtered):,} contactos | {df_filtered['counselor'].nunique()} conselheiros | {df_filtered['facility'].nunique()} unidades sanitárias*")

# ─── Análise Cumulativa (desde o início do programa) ─────────────────────────
with st.expander("📅 Visão Geral do Programa — Análise Cumulativa (desde o início até à data mais recente)", expanded=False):

    df_cum = df_filtered.copy()

    # Calcular intervalo de datas
    if "test_date" in df_cum.columns:
        dates_valid = df_cum["test_date"].dropna()
        date_min = dates_valid.min()
        date_max = dates_valid.max()
        n_months = max(1, round((date_max - date_min).days / 30))
        st.info(
            f"🗓️ **Período:** {date_min.strftime('%d/%m/%Y')} → {date_max.strftime('%d/%m/%Y')}  "
            f"({n_months} meses de programa)"
        )
    else:
        st.warning("Coluna de data de testagem não disponível.")
        date_min = date_max = None

    # KPIs cumulativos
    cum_tested    = int(df_cum["was_tested"].sum())
    cum_pos       = int(df_cum["is_positive"].sum())
    cum_linked    = int(df_cum[df_cum["is_positive"]]["is_linked"].sum())
    cum_consented = int(df_cum["consented"].sum())
    cum_eligible  = int(df_cum["eligible_bool"].sum())

    pos_pct_cum   = cum_pos / cum_tested * 100 if cum_tested > 0 else 0
    link_pct_cum  = cum_linked / cum_pos * 100 if cum_pos > 0 else 0
    cons_pct_cum  = cum_consented / cum_eligible * 100 if cum_eligible > 0 else 0
    test_comp_cum = cum_tested / cum_consented * 100 if cum_consented > 0 else 0

    cc1, cc2, cc3, cc4, cc5, cc6 = st.columns(6)
    cc1.metric("🔍 Total Testados",   f"{cum_tested:,}")
    cc2.metric("🦠 HIV+ Encontrados", f"{cum_pos:,}")
    cc3.metric("📈 Positividade",     f"{pos_pct_cum:.1f}%")
    cc4.metric("🔗 Linkagem",         f"{link_pct_cum:.1f}%")
    cc5.metric("📋 Consentimento",    f"{cons_pct_cum:.1f}%")
    cc6.metric("✅ Conclusão Testagem", f"{test_comp_cum:.1f}%")

    st.markdown("---")

    # Tendência Mensal — Positivos encontrados e taxa de positividade
    if "test_date" in df_cum.columns and date_min is not None:
        df_cum["month_period"] = df_cum["test_date"].dt.to_period("M")
        monthly = (
            df_cum[df_cum["was_tested"]]
            .groupby("month_period")
            .agg(
                n_testados=("was_tested", "sum"),
                n_positivos=("is_positive", "sum"),
            )
            .reset_index()
        )
        monthly["month_str"]  = monthly["month_period"].astype(str)
        monthly["positividade"] = (monthly["n_positivos"] / monthly["n_testados"] * 100).round(1)

        col_trend1, col_trend2 = st.columns(2)

        with col_trend1:
            fig_pos = px.bar(
                monthly, x="month_str", y="n_positivos",
                title="HIV+ Encontrados por Mês (cumulativo)",
                labels={"month_str": "Mês", "n_positivos": "HIV+ Encontrados"},
                color="n_positivos",
                color_continuous_scale=["#FFC107", "#DC3545"],
            )
            fig_pos.update_layout(height=300, showlegend=False, xaxis_tickangle=-45)
            st.plotly_chart(fig_pos, use_container_width=True)

        with col_trend2:
            fig_rate = px.line(
                monthly, x="month_str", y="positividade",
                title="Taxa de Positividade Mensal (%)",
                labels={"month_str": "Mês", "positividade": "Positividade (%)"},
                markers=True,
            )
            fig_rate.update_traces(line_color="#DC3545", marker_color="#DC3545")
            fig_rate.update_layout(height=300, xaxis_tickangle=-45)
            st.plotly_chart(fig_rate, use_container_width=True)

    st.markdown("---")

    # Desempenho por Província (cumulativo)
    if "province" in df_cum.columns:
        prov_agg = (
            df_cum[df_cum["was_tested"]]
            .groupby("province")
            .agg(
                Testados=("was_tested", "sum"),
                Positivos=("is_positive", "sum"),
            )
            .reset_index()
        )
        prov_agg["Positividade (%)"] = (prov_agg["Positivos"] / prov_agg["Testados"] * 100).round(1)
        prov_agg.columns = ["Província", "Testados", "HIV+", "Positividade (%)"]

        col_pt, col_pc = st.columns([1, 2])
        with col_pt:
            st.markdown("**Por Província**")
            st.dataframe(prov_agg, use_container_width=True, hide_index=True)
        with col_pc:
            fig_prov = px.bar(
                prov_agg, x="Província", y="HIV+",
                color="Positividade (%)",
                color_continuous_scale=["#FFC107", "#DC3545"],
                title="HIV+ por Província (total do programa)",
                text="HIV+",
            )
            fig_prov.update_traces(textposition="outside")
            fig_prov.update_layout(height=300, showlegend=False)
            st.plotly_chart(fig_prov, use_container_width=True)


# ─── KPIs ─────────────────────────────────────────────────────────────────────
st.markdown("### Indicadores Chave")

n_pos      = int(df_filtered["is_positive"].sum())
n_linked   = int(df_filtered[df_filtered["is_positive"]]["is_linked"].sum())
n_eligible = int(df_filtered["eligible_bool"].sum())
n_consented = int(df_filtered["consented"].sum())
n_tested   = int(df_filtered["was_tested"].sum())

positivity_pct  = n_pos / n_tested * 100 if n_tested > 0 else 0
testing_comp    = n_tested / n_consented * 100 if n_consented > 0 else 0
consent_pct     = n_consented / n_eligible * 100 if n_eligible > 0 else 0
linkage_pct     = n_linked / n_pos * 100 if n_pos > 0 else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("🦠 Positividade",       f"{positivity_pct:.1f}%",  help="% de contactos testados que são HIV+")
c2.metric("✅ Conclusão Testagem", f"{testing_comp:.1f}%",    help="% de consentidos efectivamente testados (alvo ≥95%)")
c3.metric("📋 Consentimento",      f"{consent_pct:.1f}%",     help="% de elegíveis que consentiram (alvo ≥90%)")
c4.metric("🔴 HIV+ Encontrados",   f"{n_pos:,}")
c5.metric("🔗 Linkagem",           f"{linkage_pct:.1f}%",     help="% de HIV+ ligados aos cuidados (monitorar)")

st.markdown("---")

# ─── Nível Distrito ───────────────────────────────────────────────────────────
if view_level == "Distrito":
    dist_df = compute_district_metrics(df_filtered)

    if dist_df.empty:
        st.info("Sem dados de distrito para a selecção actual.")
        st.stop()

    st.markdown("### Desempenho por Distrito")

    display_dist = dist_df[["district", "province",
                             "district_median_test_positivity",
                             "district_median_testing_completion",
                             "district_median_consent_rate",
                             "n_contacts_total"]].copy()
    display_dist.columns = ["Distrito", "Província", "Positividade (%)", "Conclusão Testagem (%)", "Consentimento (%)", "Total Contactos"]

    display_dist["Estado 🚦"] = display_dist.apply(
        lambda r: "🔴" if r["Conclusão Testagem (%)"] < 70
        else "🟡" if r["Conclusão Testagem (%)"] < 90
        else "🟢", axis=1
    )

    st.dataframe(display_dist.round(1), use_container_width=True, hide_index=True)

    if len(dist_df) > 0:
        fig = px.bar(
            dist_df.sort_values("district_median_test_positivity"),
            x="district",
            y="district_median_test_positivity",
            color="district_median_test_positivity",
            color_continuous_scale=["#DC3545", "#FFC107", "#28A745"],
            title="Taxa de Positividade Mediana por Distrito",
            labels={"district_median_test_positivity": "Positividade (%)", "district": "Distrito"},
        )
        fig.update_layout(height=350, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

# ─── Nível Unidade Sanitária ──────────────────────────────────────────────────
elif view_level == "Unidade Sanitária":
    fac_flagged = flag_facilities(df_filtered)

    if fac_flagged.empty:
        st.info("Sem dados de unidades sanitárias disponíveis.")
        st.stop()

    st.markdown("### Desempenho das Unidades Sanitárias vs Mediana do Distrito")
    st.markdown("*🔴 ≥10% abaixo da mediana do distrito | 🟡 atenção | 🟢 em dia*")

    cols_show = ["facility", "district", "n_contacts_total", "n_counselors",
                 "median_test_positivity", "median_testing_completion",
                 "median_consent_rate", "severity", "flags"]
    cols_show = [c for c in cols_show if c in fac_flagged.columns]
    display_fac = fac_flagged[cols_show].copy()
    rename_map = {
        "facility": "Unidade", "district": "Distrito",
        "n_contacts_total": "Contactos", "n_counselors": "Conselheiros",
        "median_test_positivity": "Positividade (%)",
        "median_testing_completion": "Conclusão Testagem (%)",
        "median_consent_rate": "Consentimento (%)",
        "severity": "Estado", "flags": "Sinalizações"
    }
    display_fac = display_fac.rename(columns=rename_map)
    if "Estado" in display_fac.columns:
        display_fac["Estado"] = display_fac["Estado"].map(
            {"red": "🔴 Crítico", "yellow": "🟡 Atenção", "green": "🟢 Em Dia"}
        )
    st.dataframe(display_fac.round(1), use_container_width=True, hide_index=True)

    if "district_median_test_positivity" in fac_flagged.columns and "median_test_positivity" in fac_flagged.columns:
        fig = px.scatter(
            fac_flagged,
            x="district_median_test_positivity",
            y="median_test_positivity",
            color="severity",
            color_discrete_map={"red": "#DC3545", "yellow": "#FFC107", "green": "#28A745"},
            hover_name="facility",
            hover_data={"district": True, "n_contacts_total": True, "severity": False},
            title="Positividade US vs Mediana do Distrito",
            labels={
                "district_median_test_positivity": "Mediana Distrito (%)",
                "median_test_positivity": "Mediana Unidade (%)",
            },
        )
        max_val = max(fac_flagged["district_median_test_positivity"].max(),
                      fac_flagged["median_test_positivity"].max())
        fig.add_trace(go.Scatter(
            x=[0, max_val], y=[0, max_val],
            mode="lines", line=dict(dash="dash", color="gray"),
            name="Linha de paridade",
        ))
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

# ─── Nível Conselheiro ────────────────────────────────────────────────────────
elif view_level == "Conselheiro":
    coun_flagged = flag_counselors(df_filtered)

    if coun_flagged.empty:
        st.info("Sem dados de conselheiros disponíveis.")
        st.stop()

    facilities = ["Todas"] + sorted(coun_flagged["facility"].dropna().unique().tolist())
    sel_facility = st.selectbox("Detalhar por Unidade Sanitária", facilities)

    if sel_facility != "Todas":
        display_coun = coun_flagged[coun_flagged["facility"] == sel_facility]
    else:
        display_coun = coun_flagged

    st.markdown(f"### Conselheiros — {sel_facility if sel_facility != 'Todas' else 'Todas as Unidades'}")
    st.markdown("*Comparado com a mediana da unidade. 🔴 = ≥10% abaixo da mediana.*")

    cols_to_show = [
        "counselor", "facility", "district", "n_contacts",
        "test_positivity", "facility_median_test_positivity",
        "testing_completion", "consent_rate",
        "severity", "flags"
    ]
    cols_to_show = [c for c in cols_to_show if c in display_coun.columns]
    disp = display_coun[cols_to_show].copy()
    rename_c = {
        "counselor": "Conselheiro", "facility": "Unidade", "district": "Distrito",
        "n_contacts": "Contactos",
        "test_positivity": "Positividade (%)",
        "facility_median_test_positivity": "Mediana US (%)",
        "testing_completion": "Conclusão (%)",
        "consent_rate": "Consentimento (%)",
        "severity