"""
app.py
──────
RISE AI Technical Advisor — Aplicacao Principal Streamlit

Ponto de entrada. Configura pagina, estado de sessao e navegacao.
Executar com: streamlit run app.py
"""

import streamlit as st
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

st.set_page_config(
    page_title="RISE ICT — Consultor Tecnico IA",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

if "df" not in st.session_state:
    st.session_state.df = None
if "quality_report" not in st.session_state:
    st.session_state.quality_report = None
if "orch_result" not in st.session_state:
    st.session_state.orch_result = None
if "last_upload_filename" not in st.session_state:
    st.session_state.last_upload_filename = None

st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #00539C, #0077CC);
        color: white;
        padding: 1rem 1.5rem;
        border-radius: 8px;
        margin-bottom: 1.5rem;
    }
    .main-header h1 { color: white; margin: 0; font-size: 1.6rem; }
    .main-header p  { color: #CCE4FF; margin: 0; font-size: 0.9rem; }

    .metric-card {
        background: white;
        border: 1px solid #E0E0E0;
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
    }
    .metric-card .value { font-size: 1.8rem; font-weight: bold; }
    .metric-good  { border-top: 4px solid #28A745; }
    .metric-warn  { border-top: 4px solid #FFC107; }
    .metric-bad   { border-top: 4px solid #DC3545; }

    .flag-red    { background: #FFF5F5; border-left: 5px solid #DC3545; padding: 0.8rem; border-radius: 4px; margin: 0.3rem 0; }
    .flag-yellow { background: #FFFBF0; border-left: 5px solid #FFC107; padding: 0.8rem; border-radius: 4px; margin: 0.3rem 0; }
    .flag-green  { background: #F0FFF4; border-left: 5px solid #28A745; padding: 0.8rem; border-radius: 4px; margin: 0.3rem 0; }

    .sidebar-status { font-size: 0.8rem; color: #888; padding: 0.5rem 0; }

    #MainMenu { visibility: hidden; }
    footer    { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ─── Barra lateral ────────────────────────────────────────────────────────────
with st.sidebar:
    logo_path = Path(__file__).parent / "Jhpiego_Logo_Digital.jpg"
    if not logo_path.exists():
        logo_path = Path(__file__).parent / "assets" / "jhpiego_logo.png"
    if logo_path.exists():
        st.image(str(logo_path), use_container_width=True)
    else:
        st.markdown("**jhpiego**")
    st.markdown("---")
    st.markdown("### 🏥 RISE ICT Advisor")
    st.markdown("Plataforma de supervisão inteligente")
    st.markdown("---")

    if st.session_state.df is not None:
        df = st.session_state.df
        st.success(f"✅ **Dados carregados**")
        st.markdown(f"<div class='sidebar-status'>"
                    f"📁 {st.session_state.last_upload_filename or 'dados.csv'}<br>"
                    f"📊 {len(df):,} contactos<br>"
                    f"👥 {df['counselor'].nunique()} conselheiros<br>"
                    f"🏥 {df['facility'].nunique()} unidades sanitárias<br>"
                    f"📍 {df['district'].nunique()} distritos"
                    f"</div>", unsafe_allow_html=True)
    else:
        st.warning("⚠️ Nenhum dado carregado")
        st.markdown("<div class='sidebar-status'>Carregue um CSV na página de Dados para começar.</div>",
                    unsafe_allow_html=True)

    st.markdown("---")

    api_key = os.getenv("GROK_API_KEY", "")
    if api_key and api_key.startswith("gsk_"):
        st.success("🤖 Grok API: Conectado")
    else:
        st.warning("🤖 Grok API: Não configurado")
        with st.expander("Como configurar"):
            st.markdown(
                "Adicione `GROK_API_KEY=gsk_...` ao seu ficheiro `.env` "
                "ou ao Streamlit secrets (`secrets.toml`)."
            )

    st.markdown("---")
    st.markdown("<div class='sidebar-status'>Programa RISE / JHPIEGO<br>v1.0.0</div>",
                unsafe_allow_html=True)

# ─── Página inicial ────────────────────────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>🏥 RISE ICT — Consultor Técnico IA</h1>
    <p>Programa RISE JHPIEGO · Moçambique (Zambézia & Manica) · Plataforma de Inteligência de Supervisão</p>
</div>
""", unsafe_allow_html=True)

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown("""
    ### 📤 1. Carregar Dados
    Carregue a lista de linha ICT semanal em CSV do DHIS2. O sistema valida a qualidade dos dados automaticamente.
    """)
    if st.button("→ Ir para Upload", use_container_width=True, type="primary"):
        st.switch_page("pages/01_Upload.py")

with col2:
    st.markdown("""
    ### 📊 2. Painel de Controlo
    Painel de desempenho interactivo. Detalhe de distrito → unidade → conselheiro.
    """)
    if st.button("→ Ir para Painel", use_container_width=True):
        st.switch_page("pages/02_Dashboard.py")

with col3:
    st.markdown("""
    ### 🤖 3. Análise IA
    Executar os 3 fluxos: Sinalização, Alocação de Supervisão, Análise de Causa Raiz.
    """)
    if st.button("→ Ir para Análise", use_container_width=True):
        st.switch_page("pages/03_Analysis.py")

with col4:
    st.markdown("""
    ### 📧 4. Relatórios
    Enviar resumos PDF e dashboards HTML por email. Configurar envio automático semanal.
    """)
    if st.button("→ Ir para Relatórios", use_container_width=True):
        st.switch_page("pages/04_Schedule.py")

st.markdown("---")

# ─── Resumo rápido se dados carregados ────────────────────────────────────────
if st.session_state.df is not None:
    st.markdown("### 📈 Resumo Rápido")
    df = st.session_state.df

    from tools.compute_metrics import compute_district_metrics, format_pct
    dist = compute_district_metrics(df)

    if not dist.empty:
        cols = st.columns(min(len(dist), 6))
        for i, (_, row) in enumerate(dist.iterrows()):
            if i >= 6:
                break
            with cols[i]:
                positivity = row.get("district_median_test_positivity", float("nan"))
                testing    = row.get("district_median_testing_completion", float("nan"))
                try:
                    color_cls = "metric-good" if float(testing) >= 90 else "metric-warn" if float(testing) >= 70 else "metric-bad"
                except Exception:
                    color_cls = "metric-warn"
                st.markdown(f"""
                <div class="metric-card {color_cls}">
                    <div style="font-size:0.85rem;color:#666">{row['district']}</div>
                    <div class="value">{format_pct(positivity)}</div>
                    <div style="font-size:0.75rem;color:#888">Positividade</div>
                    <div style="font-size:0.75rem;color:#888">{int(row.get('n_contacts_total',0)):,} contactos</div>
                </div>
                """, unsafe_allow_html=True)

    st.markdown("")
    if st.button("🚀 Executar Análise Completa", type="primary"):
        st.switch_page("pages/03_Analysis.py")
else:
    st.info("👆 Comece por carregar a lista de linha ICT em CSV usando a página **Carregar Dados**.")
