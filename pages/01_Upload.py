"""
01_Upload.py
────────────
Página 1: Upload de Dados + Verificação de Qualidade
"""

import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import date
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.data_loader import load_csv_from_bytes
from core.data_quality import run_quality_checks
from core.period_utils import get_last_date, get_analysis_window, get_trend_window, filter_to_period, period_label

st.set_page_config(page_title="Carregar Dados — RISE ICT", page_icon="📤", layout="wide")

st.markdown("## 📤 Carregar Lista de Linha ICT")
st.markdown("Carregue o CSV de exportação semanal do DHIS2. O sistema valida automaticamente a qualidade dos dados.")

# ─── Upload ────────────────────────────────────────────────────────────────────
uploaded_file = st.file_uploader(
    "Seleccionar ficheiro CSV ou Excel (exportação DHIS2)",
    type=["csv", "xlsx", "xls"],
    help="Carregue o CSV ou Excel 'Base de Dados Principal' exportado do DHIS2.",
)

if uploaded_file is not None:
    with st.spinner(f"A carregar e validar {uploaded_file.name}..."):
        try:
            file_bytes = uploaded_file.read()
            df = load_csv_from_bytes(file_bytes, filename=uploaded_file.name)
            quality_report = run_quality_checks(df)

            # Período de análise: 4 semanas até à última data dos dados
            last_date    = get_last_date(df) or date.today()
            p_start, p_end = get_analysis_window(last_date)
            t_start, t_end = get_trend_window(last_date)
            df_period = filter_to_period(df, p_start, p_end)
            df_trend  = filter_to_period(df, t_start, t_end)

            st.session_state.df                    = df           # histórico completo
            st.session_state.df_period             = df_period    # 4 semanas actuais
            st.session_state.df_trend              = df_trend     # 4 semanas anteriores
            st.session_state.period_start          = p_start
            st.session_state.period_end            = p_end
            st.session_state.upload_date           = last_date
            st.session_state.quality_report        = quality_report
            st.session_state.last_upload_filename  = uploaded_file.name

        except ValueError as e:
            st.error(f"❌ Erro ao carregar ficheiro: {e}")
            st.stop()
        except Exception as e:
            st.error(f"❌ Erro inesperado: {e}")
            st.stop()

    st.success(f"✅ **{uploaded_file.name}** carregado com sucesso!")

    # Banner do período de análise
    n_periodo = len(df_period)
    st.info(
        f"📅 **Período de análise:** {period_label(p_start, p_end)}  "
        f"(4 semanas até {last_date.strftime('%d/%m/%Y')} — última data dos dados)  "
        f"| {n_periodo:,} registos no período | {len(df):,} no total"
    )
    if n_periodo == 0:
        st.warning(
            "⚠️ Nenhum registo encontrado nas últimas 4 semanas dos dados. "
            "Verifique as datas no ficheiro."
        )

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Contactos (4 semanas)", f"{n_periodo:,}")
    col2.metric("Conselheiros", df_period["counselor"].nunique() if n_periodo > 0 else 0)
    col3.metric("Unidades Sanitárias", df_period["facility"].nunique() if n_periodo > 0 else 0)
    col4.metric("Distritos", df_period["district"].nunique() if n_periodo > 0 else 0)
    col5.metric("Qualidade dos Dados", f"{quality_report.score:.0f}/100")

    st.markdown("---")

    st.markdown("### 🔍 Relatório de Qualidade de Dados")

    if quality_report.passed:
        st.success(f"✅ Verificação APROVADA (pontuação: {quality_report.score:.1f}/100)")
    else:
        st.error(f"❌ Verificação REPROVADA (pontuação: {quality_report.score:.1f}/100) — problemas críticos encontrados.")

    if quality_report.issues:
        for issue in quality_report.issues:
            if issue.severity == "critical":
                icon = "🔴"
            elif issue.severity == "warning":
                icon = "🟡"
            else:
                icon = "🔵"

            with st.expander(f"{icon} [{issue.severity.upper()}] {issue.check} — {issue.affected_rows:,} registos ({issue.affected_pct:.1f}%)"):
                st.write(issue.description)
                if issue.examples:
                    st.write("**Exemplos:**", ", ".join(str(e) for e in issue.examples))
    else:
        st.success("Nenhum problema de qualidade detectado.")

    st.markdown("---")

    st.markdown("### 👀 Pré-visualização dos Dados")

    province_filter = st.selectbox(
        "Filtrar por Província",
        ["Todas"] + sorted(df["province"].dropna().unique().tolist()),
    )

    preview_df = df if province_filter == "Todas" else df[df["province"] == province_filter]

    display_cols = [
        "province", "district", "facility", "counselor",
        "contact_type", "contact_age", "contact_sex",
        "consented", "was_tested", "is_positive", "is_linked",
        "linkage", "test_result",
    ]
    display_cols = [c for c in display_cols if c in preview_df.columns]

    st.dataframe(
        preview_df[display_cols].head(100),
        use_container_width=True,
        hide_index=True,
    )

    st.caption(f"Mostrando os primeiros 100 de {len(preview_df):,} registos para a província seleccionada.")